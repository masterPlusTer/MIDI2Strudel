"""MIDI-to-Strudel converter with numbered output filenames.

Usage:
    python midi_to_strudel.py
    python midi_to_strudel.py violin.mid cello.mid
    python midi_to_strudel.py path/to/midi_folder

When no arguments are supplied, every .mid and .midi file found next to this
script is processed.

Each input MIDI file is converted independently and written to its own
.strudel file inside output/.

Important limitations:
- One note-containing internal track is converted from each MIDI file.
- By default, the internal track with the most note_on events is selected.
- The first tempo and first time signature found in each MIDI are used.
- Notes crossing a bar boundary are retriggered in the following bar.
"""

from __future__ import annotations

import sys
import re
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

TRACK: int | None = None
# None = choose the internal MIDI track with the most note_on events
# inside each input MIDI file.
# Set an integer such as 1 or 2 to force that internal track in every file.

NORMALIZE_START = True
# Remove silence before the first note in each exported MIDI file.

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


WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


def safe_output_stem(value: str) -> str:
    """Return a portable filename stem for Windows, macOS, and Linux."""

    # Replace characters forbidden by Windows and characters that commonly
    # cause trouble in shells, URLs, editors, and generated links.
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)

    # Keep letters, numbers, spaces, dots, underscores, hyphens, and Unicode
    # letters, while replacing punctuation such as #, %, &, quotes, and brackets.
    value = "".join(
        character
        if character.isalnum() or character in {" ", ".", "_", "-"}
        else "_"
        for character in value
    )

    # Collapse repeated whitespace and underscores.
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"_+", "_", value)

    # Windows does not allow filenames ending in a dot or space.
    value = value.strip(" ._")

    if not value:
        value = "midi_output"

    # Windows reserves these names even when an extension is present.
    if value.casefold() in WINDOWS_RESERVED_NAMES:
        value = f"{value}_file"

    # Leave room for the .strudel extension and long parent paths.
    return value[:120].rstrip(" ._") or "midi_output"


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
# Input discovery
# ---------------------------------------------------------------------------

def midi_files_in_folder(folder: Path) -> list[Path]:
    files = list(folder.glob("*.mid")) + list(folder.glob("*.midi"))
    return sorted(path.resolve() for path in files if path.is_file())


def find_midi_files() -> list[Path]:
    if len(sys.argv) == 1:
        folder = Path(__file__).resolve().parent
        files = midi_files_in_folder(folder)

        if not files:
            raise SystemExit(
                "No .mid or .midi files were found next to this script."
            )

        return files

    found: list[Path] = []

    for argument in sys.argv[1:]:
        path = Path(argument).expanduser()

        if not path.is_absolute():
            path = Path.cwd() / path

        path = path.resolve()

        if not path.exists():
            raise SystemExit(f"File or folder not found: {path}")

        if path.is_dir():
            found.extend(midi_files_in_folder(path))
            continue

        if path.suffix.lower() not in {".mid", ".midi"}:
            raise SystemExit(f"The file does not appear to be MIDI: {path}")

        found.append(path)

    unique_files = list(dict.fromkeys(found))

    if not unique_files:
        raise SystemExit("No MIDI files were found.")

    return unique_files


# ---------------------------------------------------------------------------
# MIDI information
# ---------------------------------------------------------------------------

def count_notes(track: mido.MidiTrack) -> int:
    return sum(
        1
        for msg in track
        if msg.type == "note_on" and msg.velocity > 0
    )


def track_name(track: mido.MidiTrack) -> str:
    for msg in track:
        if msg.type == "track_name" and msg.name.strip():
            return msg.name.strip()

    return ""


def choose_track(mid: mido.MidiFile) -> int:
    if TRACK is not None:
        if not 0 <= TRACK < len(mid.tracks):
            raise ValueError(
                f"TRACK={TRACK} does not exist. "
                f"This MIDI contains {len(mid.tracks)} internal tracks."
            )

        if count_notes(mid.tracks[TRACK]) == 0:
            raise ValueError(
                f"Internal track {TRACK} does not contain usable notes."
            )

        return TRACK

    counts = [count_notes(track) for track in mid.tracks]

    if not counts or max(counts) == 0:
        raise ValueError("The MIDI does not contain usable notes.")

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
            "QUANTIZATION must be divisible by 4. Use 8, 16, or 32."
        )

    return int(value)


def quantize(notes: list[NoteEvent]) -> list[NoteEvent]:
    grid = steps_per_beat()
    result: list[NoteEvent] = []

    for event in notes:
        start_step = round(event.start * grid)
        end_step = round(event.end * grid)

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
    """Split overlapping notes into monophonic voices."""

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

        start_step = max(start_step, cursor)

        if end_step <= start_step:
            continue

        add_rest(segments, start_step - cursor)

        duration_steps = end_step - start_step
        segments.append((note_name(event.note), duration_steps))
        cursor = end_step

    add_rest(segments, bar_steps - cursor)

    if not segments:
        return "~"

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
    track_index: int,
    selected_track_name: str,
    numerator: int,
    denominator: int,
) -> str:
    nonempty_voices = [voice for voice in voices if voice]

    if not nonempty_voices:
        raise ValueError("No pattern could be generated.")

    bar_length_beats = numerator * (4 / denominator)

    final_time = max(
        event.end
        for voice in nonempty_voices
        for event in voice
    )

    total_bars = max(
        1,
        int(-(final_time // -bar_length_beats)),
    )

    voice_definitions = [
        render_voice(
            notes=voice,
            total_bars=total_bars,
            bar_length_beats=bar_length_beats,
            voice_number=index,
        )
        for index, voice in enumerate(nonempty_voices, start=1)
    ]

    if len(nonempty_voices) == 1:
        body = "voice1"
    else:
        names = ",\n  ".join(
            f"voice{index}"
            for index in range(1, len(nonempty_voices) + 1)
        )

        body = (
            "stack(\n"
            f"  {names}\n"
            ")"
        )

    definitions = "\n\n".join(voice_definitions)
    normalized_comment = "yes" if NORMALIZE_START else "no"

    return (
        "// Generated by midi_to_strudel.py\n"
        f"// Source MIDI file: {source.name}\n"
        f"// Selected internal track: {track_index}\n"
        f"// Internal track name: {selected_track_name or '(unnamed)'}\n"
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
# File processing
# ---------------------------------------------------------------------------

def process_midi(
    midi_path: Path,
    output_dir: Path,
    output_index: int,
) -> Path:
    print(f"Checking: {midi_path.name}")
    print(f"  Full path: {midi_path!r}")
    print(f"  Exists: {midi_path.exists()}")
    print(f"  Is file: {midi_path.is_file()}")

    if not midi_path.exists():
        raise ValueError(
            "The MIDI path does not exist according to Python. "
            "----"
        )

    try:
        mid = mido.MidiFile(str(midi_path))
    except FileNotFoundError as exc:
        raise ValueError(
            "MIDI file does not exist "
            f"even though it was discovered in the folder: {midi_path!r}"
        ) from exc
    except (OSError, EOFError, ValueError) as exc:
        raise ValueError(f"The MIDI file could not be read: {exc}") from exc

    track_index = choose_track(mid)
    selected_track = mid.tracks[track_index]
    selected_track_name = track_name(selected_track)

    bpm = first_bpm(mid)
    numerator, denominator = first_time_signature(mid)

    raw_notes = extract_notes(mid, track_index)
    notes = normalize_start(quantize(raw_notes))

    if not notes:
        raise ValueError(
            f"Internal track {track_index} contains no convertible notes."
        )

    voices = separate_voices(notes)

    code = render_strudel(
        voices=voices,
        bpm=bpm,
        source=midi_path,
        track_index=track_index,
        selected_track_name=selected_track_name,
        numerator=numerator,
        denominator=denominator,
    )

    output_path = (
        output_dir
        / f"track_{output_index:02d}.strudel"
    )

    output_path.write_text(code, encoding="utf-8")

    print(f"Source: {midi_path.name!r}")
    print(f"Output number: {output_index:02d}")
    print(f"Selected internal track: {track_index}")
    print(f"Track name: {selected_track_name or '(unnamed)'}")
    print(f"Extracted notes: {len(raw_notes)}")
    print(f"Generated voices: {len(voices)}")
    print(f"Saved: {output_path}")
    print()

    return output_path


# ---------------------------------------------------------------------------
# Main program
# ---------------------------------------------------------------------------

def main() -> None:
    midi_files = find_midi_files()

    output_dir = Path(__file__).resolve().parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    created_files: list[Path] = []
    failed_files: list[tuple[Path, str]] = []

    print(f"Found {len(midi_files)} MIDI file(s).")
    print()

    mapping_lines = [
        "Output file\tSource MIDI file"
    ]

    for output_index, midi_path in enumerate(
        midi_files,
        start=1,
    ):
        try:
            output_path = process_midi(
                midi_path,
                output_dir,
                output_index,
            )
            created_files.append(output_path)
            mapping_lines.append(
                f"{output_path.name}\t{midi_path.name}"
            )
        except ValueError as exc:
            failed_files.append((midi_path, str(exc)))
            print(f"Skipped: {midi_path.name!r}")
            print(f"Reason: {exc}")
            print()

    mapping_path = output_dir / "track_mapping.txt"
    mapping_path.write_text(
        "\n".join(mapping_lines) + "\n",
        encoding="utf-8",
    )

    print(f"Mapping saved: {mapping_path}")
    print()

    print(
        f"Finished. Created {len(created_files)} "
        f"Strudel file(s)."
    )

    if failed_files:
        print(f"Skipped {len(failed_files)} MIDI file(s).")


if __name__ == "__main__":
    main()
