"""
Discord slash commands for the resource optimizer:  /optimize  and  /optimizehelp

Hooked into the bot with two lines in discord_bot.py:
    from optimizer_commands import register_optimizer_commands
    register_optimizer_commands(tree)

The optimizer is CPU-heavy (seconds to tens of seconds), so it runs in a worker thread,
with a limit on simultaneous jobs and one job per user at a time.
"""
import asyncio
import contextlib
import io
import logging
from dataclasses import dataclass
from typing import Optional

import discord
from discord import app_commands

import resource_optimizer as ro

log = logging.getLogger("aether.optimizer")

# ----------------------------------------------------------------------------
# Configuration (edit freely)
# ----------------------------------------------------------------------------
MAX_PRODUCERS = 19
MAX_NAME_LEN = 16
MAX_AMOUNT = 10_000_000
MAX_FILE_BYTES = 20_000
# Shown to users; set to the real order of the 4 resources
RESOURCE_LABELS = ("Wood", "Stone", "Iron", "Food")
# effort -> (search seconds, target sets re-solved with integers, seconds per integer solve)
EFFORTS = {"quick": (5, 2, 3), "normal": (15, 3, 5), "thorough": (30, 5, 8)}
MAX_CONCURRENT_JOBS = 2   # optimizations running at the same time
MAX_WAITING = 4           # extra jobs allowed to queue before new ones are refused

OBJECTIVE_CHOICES = [
    app_commands.Choice(name="⚖️ Balanced - each producer even, then producers even (Recommended)", value="BALANCED"),
    app_commands.Choice(name="🛡️ Max-min - raise the weakest resource", value="MAX_MIN_RES"),
    app_commands.Choice(name="📐 Min variance - equalize producer totals", value="MIN_VARIANCE"),
]
OBJECTIVE_TITLES = {"BALANCED": "Balanced", "MAX_MIN_RES": "Max-min", "MIN_VARIANCE": "Min variance"}
EFFORT_CHOICES = [
    app_commands.Choice(name="⚡ Quick (~5s)", value="quick"),
    app_commands.Choice(name="🔎 Normal (~15s, default)", value="normal"),
    app_commands.Choice(name="🧠 Thorough (~30s)", value="thorough"),
]

_semaphore: Optional[asyncio.Semaphore] = None
_inflight = 0            # running + waiting jobs
_active_users = set()    # user ids with a job in progress


def _slots():
    global _semaphore
    if _semaphore is None:  # created lazily so it binds to the bot's running loop
        _semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
    return _semaphore


@dataclass
class Params:
    objective: str
    half_last: bool
    ratio: Optional[str]
    effort: str


# ----------------------------------------------------------------------------
# Input handling
# ----------------------------------------------------------------------------
def prepare_input(text, ratio_text):
    """Parse + validate user text. Returns (names, R, ratios). Raises ro.InputError."""
    names, R = ro.parse_producers_text(text)
    if len(names) > MAX_PRODUCERS:
        raise ro.InputError(f"At most {MAX_PRODUCERS} producers are supported (got {len(names)}).")
    for n in names:
        if len(n) > MAX_NAME_LEN:
            raise ro.InputError(f"Producer names must be at most {MAX_NAME_LEN} characters: `{n[:30]}`.")
    names = [n.replace("`", "'") for n in names]
    ro.check_producers(names, R)
    if max(max(r) for r in R) > MAX_AMOUNT:
        raise ro.InputError(f"Amounts above {MAX_AMOUNT:,} are not supported.")
    ratios = ro.parse_ratio(ratio_text, len(names)) if ratio_text and ratio_text.strip() else None
    return names, R, ratios


async def _fail(interaction, message):
    """Tell the user something went wrong (private if we have not deferred yet)."""
    if interaction.response.is_done():
        await interaction.edit_original_response(content=message, embed=None, attachments=[])
    else:
        await interaction.response.send_message(message, ephemeral=True)


# ----------------------------------------------------------------------------
# Output formatting
# ----------------------------------------------------------------------------
def _code_fields(title, lines, limit=1000):
    """Split lines into embed fields (value limit 1024) holding code blocks."""
    chunks, cur, size = [], [], 0
    for ln in lines:
        if cur and size + len(ln) + 1 > limit - 8:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(ln)
        size += len(ln) + 1
    if cur:
        chunks.append(cur)
    return [(title if i == 0 else f"{title} (cont.)", "```\n" + "\n".join(c) + "\n```")
            for i, c in enumerate(chunks)]


def _num(x):
    return f"{x:,.1f}" if abs(x) >= 100 or float(x) != int(x) else f"{int(x)}"


def build_embed(res, params):
    names = res.names
    width = max(len(n) for n in names)
    half = res.weights[3] != 1
    desc = (f"**{len(names)} producers** · search: {res.mode} · {res.n_evaluated} plans "
            f"checked · {res.elapsed:.1f}s\n"
            f"Resources in order: {', '.join(RESOURCE_LABELS)}"
            + (f" ({RESOURCE_LABELS[3]} counts as half value)" if half else ""))
    embed = discord.Embed(title=f"⚙️ Resource Optimizer - {OBJECTIVE_TITLES.get(res.objective, res.objective)}",
                          description=desc, color=discord.Color.green())

    transfers = res.transfers()
    if transfers:
        lines = [f"{names[p].ljust(width)} ➜ {names[t].ljust(width)} {a}" for p, t, a in transfers]
        keepers = [names[p] for p in range(len(names)) if not res.sent[p].any()]
        if keepers:
            lines.append("")
            lines.append("Keep everything: " + ", ".join(keepers))
    else:
        lines = ["Nobody needs to send anything."]
    for name, value in _code_fields("📦 Who sends what to whom", lines):
        embed.add_field(name=name, value=value, inline=False)

    digits = max(len(str(int(v))) for v in res.final.flatten())
    lines = []
    for p, n in enumerate(names):
        cells = " ".join(str(int(v)).rjust(digits) for v in res.final[p])
        line = f"{n.ljust(width)} [{cells}]  total {_num(res.weighted_total(p))}"
        if res.ideal is not None:
            line += f" (ideal {_num(float(res.ideal[p]))})"
        lines.append(line)
    for name, value in _code_fields("📊 Final distribution", lines):
        embed.add_field(name=name, value=value, inline=False)

    lines = []
    for lab, before, after, kind in res.levels:
        arrow = "lower is better" if kind == "min" else "higher is better"
        lines.append(f"• {lab}: {_num(before)} → **{_num(after)}** *({arrow})*")
    embed.add_field(name="🎯 Objective (before → after)", value="\n".join(lines)[:1024], inline=False)

    foot = ["Every target combination was checked." if res.mode == "exhaustive"
            else "Best plan found by heuristic search - not proven optimal."]
    foot += res.notes
    if not res.valid:
        foot.append("⚠️ internal consistency check failed")
        log.error("optimizer constraint check failed for %s", names)
    embed.set_footer(text=" ".join(foot)[:2000])
    return embed


def _plain_text(res):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ro.print_result(res)
    return buf.getvalue()


# ----------------------------------------------------------------------------
# Command logic
# ----------------------------------------------------------------------------
async def handle_request(interaction, params, text):
    """Validate, run the optimizer off the event loop, and post the result."""
    global _inflight
    try:
        names, R, ratios = prepare_input(text, params.ratio)
    except ro.InputError as e:
        return await _fail(interaction, f"❌ {e}")

    uid = interaction.user.id
    if uid in _active_users:
        return await _fail(interaction, "⏳ You already have an optimization running - wait for it to finish.")
    if _inflight >= MAX_CONCURRENT_JOBS + MAX_WAITING:
        return await _fail(interaction, "⏳ The optimizer is busy right now, please try again in a minute.")
    if not interaction.response.is_done():
        await interaction.response.defer(thinking=True)

    seconds, top_k, milp_time = EFFORTS.get(params.effort, EFFORTS["normal"])
    timeout = seconds + 2 * top_k * milp_time + 30
    _active_users.add(uid)
    _inflight += 1
    try:
        async with _slots():
            res = await asyncio.wait_for(
                asyncio.to_thread(ro.optimize, params.objective, names, R,
                                  half_last=params.half_last, ratios=ratios, time_limit=seconds,
                                  top_k=top_k, milp_time=milp_time),
                timeout=timeout)
    except asyncio.TimeoutError:
        log.warning("optimizer timed out (%d producers, %s)", len(names), params.objective)
        return await _fail(interaction, "⌛ That took too long. Try **Quick** effort or fewer producers.")
    except ro.InputError as e:
        return await _fail(interaction, f"❌ {e}")
    except Exception:
        log.exception("optimizer crashed")
        return await _fail(interaction, "❌ Something went wrong while optimizing. Please check your input and try again.")
    finally:
        _active_users.discard(uid)
        _inflight -= 1

    try:
        embed = build_embed(res, params)
        none = discord.AllowedMentions.none()
        if len(embed) > 5800:  # too big for one embed: send as a text file instead
            file = discord.File(io.BytesIO(_plain_text(res).encode()), filename="optimizer_result.txt")
            await interaction.followup.send("Result was too long for an embed, see the attached file.",
                                            file=file, allowed_mentions=none)
        else:
            await interaction.followup.send(embed=embed, allowed_mentions=none)
    except Exception:
        log.exception("failed to send optimizer result")
        await _fail(interaction, "❌ I could not post the result.")


class ProducerModal(discord.ui.Modal, title="Producers"):
    producers = discord.ui.TextInput(
        label="One per line: name:r1,r2,r3,r4",
        style=discord.TextStyle.paragraph,
        placeholder="alpha:10,0,5,2\nbeta:0,9,1,4\ngamma:3,3,3,3",
        max_length=1500, required=True)

    def __init__(self, params):
        super().__init__()
        self.params = params

    async def on_submit(self, interaction: discord.Interaction):
        await handle_request(interaction, self.params, self.producers.value)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.exception("optimizer modal failed", exc_info=error)
        await _fail(interaction, "❌ Something went wrong.")


def help_embed():
    embed = discord.Embed(
        title="⚙️ Resource Optimizer Help",
        description=("Each producer picks **one target** and how much of each of its 4 resources to "
                     "send. A producer can only send what it originally owned (not what it received). "
                     "The bot finds the plan that best fits your objective."),
        color=discord.Color.blue())
    embed.add_field(name="📝 Command", inline=False, value=(
        "`/optimize objective:Balanced producers:alpha:10,0,5,2 beta:0,9,1,4 gamma:3,3,3,3`\n"
        "Leave **producers** empty to get a pop-up where you type one producer per line, "
        "or attach a CSV (`name,r1,r2,r3,r4` per line) in **file**."))
    embed.add_field(name="🎯 Objectives", inline=False, value=(
        "**Balanced** - each producer's 4 resources as even as possible; then producers even "
        "with each other (or matching **ratio**)\n"
        "**Max-min** - raise the weakest resource of the weakest producer (exact solver)\n"
        "**Min variance** - make producers' totals as equal as possible (or match **ratio**)"))
    embed.add_field(name="⚙️ Options", inline=False, value=(
        "**half_last** - resource 4 counts as half value\n"
        "**ratio** - ideal share between producers in the order given, e.g. `2:1:3` = first holds "
        "twice the second, third thrice (Balanced & Min variance)\n"
        "**effort** - Quick / Normal / Thorough search time"))
    embed.add_field(name="💡 Notes", inline=False, value=(
        f"• 2 to {MAX_PRODUCERS} producers, names up to {MAX_NAME_LEN} characters, whole numbers only\n"
        f"• Resources are read in this order: {', '.join(RESOURCE_LABELS)}\n"
        "• Up to 5 producers every combination is checked; beyond that the answer is a strong "
        "heuristic result, not a proven optimum - use Thorough or run it again\n"
        "• The ratio is a soft target: one target per producer often makes it impossible to hit exactly"))
    return embed


def register_optimizer_commands(tree: app_commands.CommandTree):
    @tree.command(name="optimizehelp", description="Show help for the resource optimizer")
    async def optimizehelp(interaction: discord.Interaction):
        await interaction.response.send_message(embed=help_embed())

    @tree.command(name="optimize", description="Plan resource transfers between producers")
    @app_commands.describe(
        objective="What to optimize for",
        producers="name:r1,r2,r3,r4 separated by spaces. Leave empty to type them in a pop-up",
        file="Alternative: a CSV with name,r1,r2,r3,r4 per line",
        half_last="Resource 4 counts as half value",
        ratio="Ideal shares between producers in input order, e.g. 2:1:3 (Balanced / Min variance)",
        effort="How long to search (default Normal)")
    @app_commands.choices(objective=OBJECTIVE_CHOICES, effort=EFFORT_CHOICES)
    async def optimize(
        interaction: discord.Interaction,
        objective: app_commands.Choice[str],
        producers: Optional[str] = None,
        file: Optional[discord.Attachment] = None,
        half_last: bool = False,
        ratio: Optional[str] = None,
        effort: Optional[app_commands.Choice[str]] = None,
    ):
        params = Params(objective.value, half_last, ratio, effort.value if effort else "normal")
        if not (producers and producers.strip()) and file is None:
            await interaction.response.send_modal(ProducerModal(params))
            return
        text = producers or ""
        if file is not None:
            if file.size > MAX_FILE_BYTES:
                await interaction.response.send_message(
                    f"❌ File too large (max {MAX_FILE_BYTES // 1000} KB).", ephemeral=True)
                return
            await interaction.response.defer(thinking=True)  # reading the attachment takes a moment
            try:
                content = (await file.read()).decode("utf-8-sig")
            except Exception:
                await _fail(interaction, "❌ I could not read that file - it must be a UTF-8 text/CSV file.")
                return
            text += "\n" + ro.clean_table_text(content)
        await handle_request(interaction, params, text)
