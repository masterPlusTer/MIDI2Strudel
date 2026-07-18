"""Simple experimental MIDI to Strudel converter.

Usage:
    python midi_to_strudel.py
    python midi_to_strudel.py song.mid

When no MIDI file is given, the script uses the first .mid or .midi file found
next to this script.

The generated Strudel code is written to output/.

Important limitations:
- Only one MIDI track is converted at a time.
- The first tempo and first time signature are used.
- Notes crossing a bar boundary are retriggered in the following bar.
"""

from __future__ import annotations

import sys
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

import mido


# ---------------------------------------------------------------------------
# Easy settings
# ---------------------------------------------------------------------------

QUANTIZATION = 16
# Number of subdivisions per whole note:
# 8  = eighth-note grid
# 16 = sixteenth-note grid
# 32 = thirty-second-note grid

SYNTH = "piano"

TRACK = None
# None = choose the MIDI track with the most note_on events.
# Set an integer such as 1 or 9 to force a particular internal MIDI track.

NORMALIZE_START = True
# When converting an isolated track, remove silence before its first note.

NOTE_NAMES = [
    "c",
    "c#",
    "d",
    "d#",
    "e",
    "f",
    "f#",
    "g",
    "g#",
    "a",
    "a#",
    "b",
]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NoteEvent:
    start: float
    duration: float
    note: int
    velocity: int

    @property
    def end(self) -> float:
        return self.start + self.duration


# ---------------------------------------------------------------------------
# MIDI loading
# ---------------------------------------------------------------------------

def find_midi_file() -> Path:
    if len(sys.argv) > 1:
        path = Path(sys.argv[1]).expanduser()

        if not path.is_absolute():
            path = Path.cwd() / path

        if not path.exists():
            raise SystemExit(f"No se encontró el archivo: {path}")

        if path.suffix.lower() not in {".mid", ".midi"}:
            raise SystemExit(f"El archivo no parece ser MIDI: {path}")

        return path

    folder = Path(__file__).resolve().parent

    files = sorted(
        list(folder.glob("*.mid"))
        + list(folder.glob("*.midi"))
    )

    if not files:
        raise SystemExit(
            "No encontré ningún archivo .mid o .midi junto a "
            "midi_to_strudel.py.\n"
            "Copia un MIDI en esta carpeta y vuelve a ejecutar el script."
        )

    return files[0]


def count_notes(track: mido.MidiTrack) -> int:
    return sum(
        1
        for msg in track
        if msg.type == "note_on" and msg.velocity > 0
    )


def choose_track(mid: mido.MidiFile) -> int:
    if TRACK is not None:
        if not 0 <= TRACK < len(mid.tracks):
            raise SystemExit(
                f"TRACK={TRACK} no existe. "
                f"El MIDI tiene {len(mid.tracks)} pistas internas."
            )

        return TRACK

    counts = [count_notes(track) for track in mid.tracks]

    if not counts or max(counts) == 0:
        raise SystemExit("El MIDI no contiene notas utilizables.")

    return max(range(len(counts)), key=counts.__getitem__)


def first_bpm(mid: mido.MidiFile) -> float:
    default_tempo = 500_000

    for msg in mido.merge_tracks(mid.tracks):
        if msg.type == "set_tempo":
            return float(mido.tempo2bpm(msg.tempo))

    return float(mido.tempo2bpm(default_tempo))


def first_time_signature(mid: mido.MidiFile) -> tuple[int, int]:
    for msg in mido.merge_tracks(mid.tracks):
        if msg.type == "time_signature":
            return msg.numerator, msg.denominator

    return 4, 4


# ---------------------------------------------------------------------------
# Note extraction
# ---------------------------------------------------------------------------

def extract_notes(
    mid: mido.MidiFile,
    track_index: int,
) -> list[NoteEvent]:
    active: dict[
        tuple[int, int],
        deque[tuple[int, int]],
    ] = defaultdict(deque)

    notes: list[NoteEvent] = []
    tick = 0

    for msg in mid.tracks[track_index]:
        tick += msg.time

        if msg.type == "note_on" and msg.velocity > 0:
            key = (msg.channel, msg.note)
            active[key].append((tick, msg.velocity))
            continue

        is_note_end = (
            msg.type == "note_off"
            or (
                msg.type == "note_on"
                and msg.velocity == 0
            )
        )

        if not is_note_end:
            continue

        key = (msg.channel, msg.note)

        if not active[key]:
            continue

        start_tick, velocity = active[key].popleft()

        if tick <= start_tick:
            continue

        notes.append(
            NoteEvent(
                start=start_tick / mid.ticks_per_beat,
                duration=(tick - start_tick) / mid.ticks_per_beat,
                note=msg.note,
                velocity=velocity,
            )
        )

    return sorted(
        notes,
        key=lambda event: (
            event.start,
            event.note,
            event.duration,
        ),
    )


# ---------------------------------------------------------------------------
# Quantization and normalization
# ---------------------------------------------------------------------------

def steps_per_beat() -> int:
    value = QUANTIZATION / 4

    if not value.is_integer():
        raise SystemExit(
            "QUANTIZATION debe ser divisible por 4. "
            "Usa 8, 16 o 32."
        )

    return int(value)


def quantize(notes: list[NoteEvent]) -> list[NoteEvent]:
    grid = steps_per_beat()
    result: list[NoteEvent] = []

    for event in notes:
        start_step = round(event.start * grid)
        end_step = round(event.end * grid)

        # Quantize the start and end separately. Quantizing only the duration
        # can gradually introduce timing errors.
        end_step = max(start_step + 1, end_step)

        result.append(
            NoteEvent(
                start=start_step / grid,
                duration=(end_step - start_step) / grid,
                note=event.note,
                velocity=event.velocity,
            )
        )

    return sorted(
        result,
        key=lambda event: (
            event.start,
            event.note,
            event.duration,
        ),
    )


def normalize_start(notes: list[NoteEvent]) -> list[NoteEvent]:
    if not notes or not NORMALIZE_START:
        return notes

    first_start = min(event.start for event in notes)

    if first_start <= 0:
        return notes

    return [
        NoteEvent(
            start=event.start - first_start,
            duration=event.duration,
            note=event.note,
            velocity=event.velocity,
        )
        for event in notes
    ]


# ---------------------------------------------------------------------------
# Voice separation
# ---------------------------------------------------------------------------

def separate_voices(
    notes: list[NoteEvent],
) -> list[list[NoteEvent]]:
    """Split overlapping notes into monophonic voices.

    This is still a heuristic, not genuine musical voice analysis.

    When multiple voices are available, the note is assigned to the voice
    whose previous pitch is closest. This produces more coherent melodic
    lines than simply choosing the first available voice.
    """

    voices: list[list[NoteEvent]] = []
    voice_ends: list[float] = []
    voice_last_notes: list[int] = []

    ordered_notes = sorted(
        notes,
        key=lambda event: (
            event.start,
            -event.duration,
            event.note,
        ),
    )

    for event in ordered_notes:
        available = [
            index
            for index, end in enumerate(voice_ends)
            if event.start >= end - 1e-9
        ]

        if available:
            best_index = min(
                available,
                key=lambda index: (
                    abs(event.note - voice_last_notes[index]),
                    voice_ends[index],
                    index,
                ),
            )

            voices[best_index].append(event)
            voice_ends[best_index] = event.end
            voice_last_notes[best_index] = event.note
            continue

        voices.append([event])
        voice_ends.append(event.end)
        voice_last_notes.append(event.note)

    return voices


# ---------------------------------------------------------------------------
# Strudel rendering
# ---------------------------------------------------------------------------

def note_name(number: int) -> str:
    octave = number // 12 - 1
    name = NOTE_NAMES[number % 12]
    return f"{name}{octave}"


def format_weighted_token(symbol: str, weight: int) -> str:
    if weight <= 1:
        return symbol

    return f"{symbol}@{weight}"


def add_rest(
    segments: list[tuple[str, int]],
    length: int,
) -> None:
    if length <= 0:
        return

    # Adjacent rests can safely be combined.
    if segments and segments[-1][0] == "~":
        previous_symbol, previous_length = segments[-1]
        segments[-1] = (
            previous_symbol,
            previous_length + length,
        )
    else:
        segments.append(("~", length))


def render_bar(
    notes: list[NoteEvent],
    bar_start: float,
    bar_length_beats: float,
) -> str:
    grid = steps_per_beat()

    bar_steps = round(bar_length_beats * grid)
    bar_end = bar_start + bar_length_beats

    segments: list[tuple[str, int]] = []
    cursor = 0

    relevant_notes = [
        event
        for event in notes
        if event.end > bar_start + 1e-9
        and event.start < bar_end - 1e-9
    ]

    for event in relevant_notes:
        segment_start = max(event.start, bar_start)
        segment_end = min(event.end, bar_end)

        start_step = round(
            (segment_start - bar_start) * grid
        )
        end_step = round(
            (segment_end - bar_start) * grid
        )

        start_step = max(0, min(bar_steps, start_step))
        end_step = max(0, min(bar_steps, end_step))

        if end_step <= start_step:
            continue

        # A voice should be monophonic, but protect against tiny rounding
        # overlaps introduced by quantization.
        start_step = max(start_step, cursor)

        if end_step <= start_step:
            continue

        add_rest(segments, start_step - cursor)

        duration_steps = end_step - start_step

        segments.append(
            (
                note_name(event.note),
                duration_steps,
            )
        )

        cursor = end_step

    add_rest(segments, bar_steps - cursor)

    if not segments:
        return "~"

    # If one event occupies the entire bar, its weight is unnecessary.
    # note("c3") and note("~") already occupy one complete cycle.
    if (
        len(segments) == 1
        and segments[0][1] == bar_steps
    ):
        return segments[0][0]

    return " ".join(
        format_weighted_token(symbol, weight)
        for symbol, weight in segments
    )


def render_voice(
    notes: list[NoteEvent],
    total_bars: int,
    bar_length_beats: float,
    voice_number: int,
) -> str:
    bar_patterns = [
        render_bar(
            notes=notes,
            bar_start=bar_index * bar_length_beats,
            bar_length_beats=bar_length_beats,
        )
        for bar_index in range(total_bars)
    ]

    lines: list[str] = []

    for bar_index, pattern in enumerate(bar_patterns, start=1):
        comma = "," if bar_index < len(bar_patterns) else ""

        lines.append(
            f'  note("{pattern}")'
            f"{comma} // bar {bar_index}"
        )

    joined = "\n".join(lines)

    return (
        f"const voice{voice_number} = cat(\n"
        f"{joined}\n"
        f').s("{SYNTH}")'
    )


def render_strudel(
    voices: list[list[NoteEvent]],
    bpm: float,
    source: Path,
    track: int,
    numerator: int,
    denominator: int,
) -> str:
    nonempty_voices = [
        voice
        for voice in voices
        if voice
    ]

    if not nonempty_voices:
        raise SystemExit(
            "No se pudo generar ningún patrón."
        )

    bar_length_beats = numerator * (4 / denominator)

    final_time = max(
        event.end
        for voice in nonempty_voices
        for event in voice
    )

    total_bars = max(
        1,
        int(
            -(
                final_time
                // -bar_length_beats
            )
        ),
    )

    voice_definitions = [
        render_voice(
            notes=voice,
            total_bars=total_bars,
            bar_length_beats=bar_length_beats,
            voice_number=index,
        )
        for index, voice in enumerate(
            nonempty_voices,
            start=1,
        )
    ]

    if len(nonempty_voices) == 1:
        body = "voice1"
    else:
        names = ",\n  ".join(
            f"voice{index}"
            for index in range(
                1,
                len(nonempty_voices) + 1,
            )
        )

        body = (
            "stack(\n"
            f"  {names}\n"
            ")"
        )

    definitions = "\n\n".join(voice_definitions)

    normalized_comment = (
        "yes" if NORMALIZE_START else "no"
    )

    return (
        "// Generated by midi_to_strudel.py\n"
        f"// Source: {source.name}\n"
        f"// Internal MIDI track: {track}\n"
        f"// BPM: {bpm:.2f}\n"
        f"// Time signature: {numerator}/{denominator}\n"
        f"// Quantization: 1/{QUANTIZATION}\n"
        f"// Voices: {len(nonempty_voices)}\n"
        f"// Bars: {total_bars}\n"
        f"// Start normalized: {normalized_comment}\n"
        "// Notes crossing bar boundaries are retriggered.\n\n"
        f"setcpm({bpm / 4:.6g})\n\n"
        f"{definitions}\n\n"
        f"{body}\n"
    )


# ---------------------------------------------------------------------------
# Main program
# ---------------------------------------------------------------------------

def main() -> None:
    midi_path = find_midi_file()

    try:
        mid = mido.MidiFile(midi_path)
    except (OSError, EOFError, ValueError) as exc:
        raise SystemExit(
            f"No se pudo leer el MIDI:\n{exc}"
        ) from exc

    track_index = choose_track(mid)
    bpm = first_bpm(mid)
    numerator, denominator = first_time_signature(mid)

    raw_notes = extract_notes(mid, track_index)

    notes = quantize(raw_notes)
    notes = normalize_start(notes)

    if not notes:
        raise SystemExit(
            f"La pista {track_index} "
            "no contiene notas convertibles."
        )

    voices = separate_voices(notes)

    code = render_strudel(
        voices=voices,
        bpm=bpm,
        source=midi_path,
        track=track_index,
        numerator=numerator,
        denominator=denominator,
    )

    output_dir = (
        Path(__file__).resolve().parent
        / "output"
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        output_dir
        / f"{midi_path.stem}.strudel"
    )

    output_path.write_text(
        code,
        encoding="utf-8",
    )

    print(f"MIDI: {midi_path.name}")
    print(
        f"Pista interna elegida: "
        f"{track_index}"
    )
    print(f"Notas extraídas: {len(raw_notes)}")
    print(f"Notas cuantizadas: {len(notes)}")
    print(f"Voces generadas: {len(voices)}")
    print(
        f"Compás: "
        f"{numerator}/{denominator}"
    )
    print(f"BPM: {bpm:.2f}")
    print(f"Resultado: {output_path}")


if __name__ == "__main__":
    main()
