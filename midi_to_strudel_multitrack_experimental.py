"""Multi-track MIDI to Strudel converter.

Creates one normalized .strudel file per MIDI track and one synchronized
combined arrangement.

Usage:
    python midi_to_strudel.py song.mid
"""

from __future__ import annotations

import math
import re
import sys
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

import mido


QUANTIZATION = 16
SYNTH = "piano"

# Individual tracks begin at their first note so they can be auditioned easily.
NORMALIZE_INDIVIDUAL_TRACKS = True

# Protects Strudel and the browser from pathological MIDI voice counts.
MAX_VOICES_PER_TRACK = 8

NOTE_NAMES = (
    "c", "c#", "d", "d#", "e", "f",
    "f#", "g", "g#", "a", "a#", "b",
)

# Common General MIDI percussion notes mapped to Strudel/Dirt sample names.
DRUM_MAP = {
    35: "bd", 36: "bd",
    37: "rim", 38: "sd", 39: "cp", 40: "sd",
    41: "lt", 43: "lt", 45: "mt", 47: "mt", 48: "ht", 50: "ht",
    42: "hh", 44: "hh", 46: "oh",
    49: "cr", 51: "ride", 52: "cr", 53: "ride",
    55: "cr", 57: "cr", 59: "ride",
}


@dataclass(frozen=True)
class NoteEvent:
    start: float
    duration: float
    note: int
    velocity: int
    channel: int

    @property
    def end(self) -> float:
        return self.start + self.duration

    @property
    def is_drum(self) -> bool:
        return self.channel == 9


@dataclass
class ConvertedTrack:
    index: int
    name: str
    notes: list[NoteEvent]
    melodic_voices: list[list[NoteEvent]]
    drum_notes: list[NoteEvent]


def find_midi_file() -> Path:
    if len(sys.argv) > 1:
        path = Path(sys.argv[1]).expanduser().resolve()
        if not path.exists():
            raise SystemExit(f"No se encontró el archivo: {path}")
        return path

    folder = Path(__file__).resolve().parent
    files = sorted([*folder.glob("*.mid"), *folder.glob("*.midi")])
    if not files:
        raise SystemExit("No encontré ningún archivo .mid o .midi.")
    return files[0]


def absolute_messages(mid: mido.MidiFile):
    """Yield merged MIDI messages with absolute tick positions."""
    absolute_tick = 0
    for message in mido.merge_tracks(mid.tracks):
        absolute_tick += message.time
        yield absolute_tick, message


def tempo_at_first_note(mid: mido.MidiFile) -> int:
    """Return the tempo active when the first audible note begins.

    This avoids choosing a placeholder tempo event at tick zero when the real
    tempo is set later in the MIDI introduction.
    """
    tempo = 500_000
    for _, message in absolute_messages(mid):
        if message.type == "set_tempo":
            tempo = message.tempo
        elif message.type == "note_on" and message.velocity > 0:
            return tempo
    return tempo


def first_time_signature(mid: mido.MidiFile) -> tuple[int, int]:
    for _, message in absolute_messages(mid):
        if message.type == "time_signature":
            return message.numerator, message.denominator
    return 4, 4


def has_tempo_changes(mid: mido.MidiFile) -> bool:
    tempos = {
        message.tempo
        for _, message in absolute_messages(mid)
        if message.type == "set_tempo"
    }
    return len(tempos) > 1


def get_track_name(track: mido.MidiTrack, index: int) -> str:
    for message in track:
        if message.type == "track_name" and message.name.strip():
            return message.name.strip()
    return f"Track {index}"


def extract_notes(mid: mido.MidiFile, track_index: int) -> list[NoteEvent]:
    active: dict[tuple[int, int], deque[tuple[int, int]]] = defaultdict(deque)
    notes: list[NoteEvent] = []
    tick = 0

    for message in mid.tracks[track_index]:
        tick += message.time

        if message.type == "note_on" and message.velocity > 0:
            active[(message.channel, message.note)].append((tick, message.velocity))
            continue

        note_end = (
            message.type == "note_off"
            or (message.type == "note_on" and message.velocity == 0)
        )
        if not note_end:
            continue

        key = (message.channel, message.note)
        if not active[key]:
            continue

        start_tick, velocity = active[key].popleft()
        if tick <= start_tick:
            continue

        notes.append(
            NoteEvent(
                start=start_tick / mid.ticks_per_beat,
                duration=(tick - start_tick) / mid.ticks_per_beat,
                note=message.note,
                velocity=velocity,
                channel=message.channel,
            )
        )

    return sorted(notes, key=lambda n: (n.start, n.channel, n.note, n.duration))


def steps_per_beat() -> int:
    if QUANTIZATION % 4:
        raise SystemExit("QUANTIZATION debe ser divisible por 4.")
    return QUANTIZATION // 4


def quantize(notes: list[NoteEvent]) -> list[NoteEvent]:
    grid = steps_per_beat()
    result: list[NoteEvent] = []

    for note in notes:
        start_step = round(note.start * grid)
        end_step = max(start_step + 1, round(note.end * grid))
        result.append(
            NoteEvent(
                start=start_step / grid,
                duration=(end_step - start_step) / grid,
                note=note.note,
                velocity=note.velocity,
                channel=note.channel,
            )
        )

    return sorted(result, key=lambda n: (n.start, n.channel, n.note, n.duration))


def normalize(notes: list[NoteEvent]) -> list[NoteEvent]:
    if not notes:
        return []
    offset = min(note.start for note in notes)
    return [
        NoteEvent(
            start=note.start - offset,
            duration=note.duration,
            note=note.note,
            velocity=note.velocity,
            channel=note.channel,
        )
        for note in notes
    ]


def shift_notes(
    notes: list[NoteEvent],
    offset: float,
) -> list[NoteEvent]:
    """Shift notes earlier by a shared offset without changing alignment."""
    return [
        NoteEvent(
            start=max(0.0, note.start - offset),
            duration=note.duration,
            note=note.note,
            velocity=note.velocity,
            channel=note.channel,
        )
        for note in notes
    ]


def separate_voices(notes: list[NoteEvent]) -> list[list[NoteEvent]]:
    voices: list[list[NoteEvent]] = []
    ends: list[float] = []
    pitches: list[int] = []

    for note in sorted(notes, key=lambda n: (n.start, -n.duration, n.note)):
        available = [
            index for index, end in enumerate(ends)
            if note.start >= end - 1e-9
        ]

        if available:
            index = min(
                available,
                key=lambda i: (abs(note.note - pitches[i]), ends[i], i),
            )
            voices[index].append(note)
            ends[index] = note.end
            pitches[index] = note.note
        elif len(voices) < MAX_VOICES_PER_TRACK:
            voices.append([note])
            ends.append(note.end)
            pitches.append(note.note)
        else:
            # Rather than creating hundreds of voices and killing Strudel,
            # place the note in the voice that becomes free first.
            index = min(range(len(voices)), key=lambda i: ends[i])
            if note.start >= ends[index] - 1e-9:
                voices[index].append(note)
                ends[index] = note.end
                pitches[index] = note.note

    return voices


def midi_note_name(number: int) -> str:
    return f"{NOTE_NAMES[number % 12]}{number // 12 - 1}"


def weighted(symbol: str, length: int) -> str:
    return symbol if length <= 1 else f"{symbol}@{length}"


def render_bar(
    notes: list[NoteEvent],
    bar_start: float,
    bar_length: float,
    drum: bool = False,
) -> str:
    grid = steps_per_beat()
    total_steps = round(bar_length * grid)
    bar_end = bar_start + bar_length
    segments: list[tuple[str, int]] = []
    cursor = 0

    relevant = [
        note for note in notes
        if note.end > bar_start + 1e-9 and note.start < bar_end - 1e-9
    ]

    for note in relevant:
        start = max(note.start, bar_start)
        end = min(note.end, bar_end)
        start_step = max(cursor, round((start - bar_start) * grid))
        end_step = min(total_steps, round((end - bar_start) * grid))

        if end_step <= start_step:
            continue

        if start_step > cursor:
            segments.append(("~", start_step - cursor))

        symbol = (
            DRUM_MAP.get(note.note, "sd")
            if drum
            else midi_note_name(note.note)
        )
        segments.append((symbol, end_step - start_step))
        cursor = end_step

    if cursor < total_steps:
        segments.append(("~", total_steps - cursor))

    if not segments:
        return "~"

    merged: list[tuple[str, int]] = []
    for symbol, length in segments:
        if merged and symbol == "~" and merged[-1][0] == "~":
            merged[-1] = ("~", merged[-1][1] + length)
        else:
            merged.append((symbol, length))

    if len(merged) == 1 and merged[0][1] == total_steps:
        return merged[0][0]

    return " ".join(weighted(symbol, length) for symbol, length in merged)


def render_pattern(
    variable: str,
    notes: list[NoteEvent],
    total_bars: int,
    bar_length: float,
    gain: float,
    drum: bool = False,
) -> str:
    bars = []
    for index in range(total_bars):
        pattern = render_bar(
            notes,
            bar_start=index * bar_length,
            bar_length=bar_length,
            drum=drum,
        )
        comma = "," if index < total_bars - 1 else ""
        bars.append(f'  {"s" if drum else "note"}("{pattern}"){comma} // bar {index + 1}')

    if drum:
        sound_chain = ".clip(0.45)"
    else:
        # Piano samples can have long natural tails. With many stacked voices
        # those tails accumulate until WebAudio reaches its polyphony limit.
        # clip() keeps each event inside its rhythmic slot.
        sound_chain = f'.s("{SYNTH}").clip(0.88)'

    return (
        f"const {variable} = cat(\n"
        + "\n".join(bars)
        + f"\n){sound_chain}.gain({gain:.4f})"
    )


def total_bars(notes: list[NoteEvent], bar_length: float) -> int:
    if not notes:
        return 1
    return max(1, math.ceil(max(note.end for note in notes) / bar_length - 1e-9))


def safe_filename(text: str) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
    return re.sub(r"\s+", " ", text).strip() or "midi_output"


def convert_tracks(mid: mido.MidiFile) -> list[ConvertedTrack]:
    result: list[ConvertedTrack] = []

    for index, track in enumerate(mid.tracks):
        notes = quantize(extract_notes(mid, index))
        if not notes:
            continue

        melodic = [note for note in notes if not note.is_drum]
        drums = [note for note in notes if note.is_drum]

        result.append(
            ConvertedTrack(
                index=index,
                name=get_track_name(track, index),
                notes=notes,
                melodic_voices=separate_voices(melodic),
                drum_notes=drums,
            )
        )

    return result


def render_track_file(
    track: ConvertedTrack,
    bpm: float,
    numerator: int,
    denominator: int,
    source_name: str,
) -> str:
    notes = normalize(track.notes) if NORMALIZE_INDIVIDUAL_TRACKS else track.notes
    melodic = [note for note in notes if not note.is_drum]
    drums = [note for note in notes if note.is_drum]
    voices = separate_voices(melodic)

    bar_length = numerator * 4 / denominator
    bars = total_bars(notes, bar_length)
    pattern_count = len(voices) + (1 if drums else 0)
    gain = min(0.65, 0.8 / math.sqrt(max(1, pattern_count)))

    definitions: list[str] = []
    names: list[str] = []

    for voice_index, voice in enumerate(voices, 1):
        name = f"track{track.index}_voice{voice_index}"
        names.append(name)
        definitions.append(
            render_pattern(name, voice, bars, bar_length, gain)
        )

    if drums:
        name = f"track{track.index}_drums"
        names.append(name)
        definitions.append(
            render_pattern(name, drums, bars, bar_length, gain, drum=True)
        )

    cpm = bpm / bar_length
    body = names[0] if len(names) == 1 else "stack(\n  " + ",\n  ".join(names) + "\n)"

    return (
        "// Generated by midi_to_strudel.py\n"
        f"// Source: {source_name}\n"
        f"// MIDI track {track.index}: {track.name}\n"
        f"// BPM: {bpm:.2f}\n"
        f"// Time signature: {numerator}/{denominator}\n\n"
        f"setcpm({cpm:.8g})\n\n"
        + "\n\n".join(definitions)
        + "\n\n"
        + body
        + "\n"
    )


def render_combined(
    tracks: list[ConvertedTrack],
    bpm: float,
    numerator: int,
    denominator: int,
    source_name: str,
) -> str:
    """Render all tracks while removing only the global leading silence.

    Every track receives the same offset, so their relative synchronization is
    preserved. This avoids combined files that appear silent because the MIDI
    contains empty measures before the first audible note.
    """
    original_notes = [
        note
        for track in tracks
        for note in track.notes
    ]

    if not original_notes:
        raise ValueError("No hay notas para combinar.")

    global_start = min(note.start for note in original_notes)

    shifted_tracks: list[ConvertedTrack] = []

    for track in tracks:
        shifted_notes = shift_notes(track.notes, global_start)
        melodic = [
            note for note in shifted_notes
            if not note.is_drum
        ]
        drums = [
            note for note in shifted_notes
            if note.is_drum
        ]

        shifted_tracks.append(
            ConvertedTrack(
                index=track.index,
                name=track.name,
                notes=shifted_notes,
                melodic_voices=separate_voices(melodic),
                drum_notes=drums,
            )
        )

    all_notes = [
        note
        for track in shifted_tracks
        for note in track.notes
    ]

    bar_length = numerator * 4 / denominator
    bars = total_bars(all_notes, bar_length)

    total_patterns = sum(
        len(track.melodic_voices)
        + (1 if track.drum_notes else 0)
        for track in shifted_tracks
    )

    # Gain is applied once to the final stack. Applying tiny gains to every
    # deeply nested pattern can become difficult to diagnose in large files.
    master_gain = min(
        0.55,
        1.05 / math.sqrt(max(1, total_patterns)),
    )

    definitions: list[str] = []
    names: list[str] = []

    for track in shifted_tracks:
        definitions.append(
            f"// Track {track.index}: {track.name}"
        )

        for voice_index, voice in enumerate(
            track.melodic_voices,
            1,
        ):
            name = (
                f"track{track.index}"
                f"_voice{voice_index}"
            )
            names.append(name)

            # Keep patterns at unity gain; control the complete mix below.
            definitions.append(
                render_pattern(
                    name,
                    voice,
                    bars,
                    bar_length,
                    1.0,
                )
            )

        if track.drum_notes:
            name = f"track{track.index}_drums"
            names.append(name)

            definitions.append(
                render_pattern(
                    name,
                    track.drum_notes,
                    bars,
                    bar_length,
                    1.0,
                    drum=True,
                )
            )

    cpm = bpm / bar_length

    if len(names) == 1:
        final_pattern = (
            f"{names[0]}.gain({master_gain:.4f})"
        )
    else:
        final_pattern = (
            "stack(\n  "
            + ",\n  ".join(names)
            + "\n)"
            + f".gain({master_gain:.4f})"
        )

    return (
        "// Generated by midi_to_strudel.py\n"
        f"// Source: {source_name}\n"
        f"// BPM: {bpm:.2f}\n"
        f"// Time signature: {numerator}/{denominator}\n"
        f"// Patterns stacked: {total_patterns}\n"
        f"// Maximum melodic voices per track: {MAX_VOICES_PER_TRACK}\n"
        f"// Piano sample clip: 0.88\n"
        f"// Removed global leading silence: {global_start:.4f} beats\n\n"
        f"setcpm({cpm:.8g})\n\n"
        + "\n\n".join(definitions)
        + "\n\n"
        + final_pattern
        + "\n"
    )


def main() -> None:
    midi_path = find_midi_file()
    mid = mido.MidiFile(midi_path)

    tempo = tempo_at_first_note(mid)
    bpm = float(mido.tempo2bpm(tempo))
    numerator, denominator = first_time_signature(mid)
    tracks = convert_tracks(mid)

    if not tracks:
        raise SystemExit("El MIDI no contiene pistas con notas.")

    output_dir = (
        Path(__file__).resolve().parent
        / "output"
        / safe_filename(midi_path.stem)
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    for track in tracks:
        path = output_dir / f"{safe_filename(midi_path.stem)}_track_{track.index:02d}.strudel"
        path.write_text(
            render_track_file(
                track, bpm, numerator, denominator, midi_path.name
            ),
            encoding="utf-8",
        )

    combined = output_dir / f"{safe_filename(midi_path.stem)}_combined.strudel"
    combined.write_text(
        render_combined(
            tracks, bpm, numerator, denominator, midi_path.name
        ),
        encoding="utf-8",
    )

    total_patterns = sum(
        len(track.melodic_voices) + (1 if track.drum_notes else 0)
        for track in tracks
    )

    print(f"MIDI: {midi_path.name}")
    print(f"BPM usado: {bpm:.2f}")
    print(f"Compás: {numerator}/{denominator}")
    print(f"Pistas con notas: {len(tracks)}")
    print(f"Patrones combinados: {total_patterns}")
    print(f"Salida: {output_dir}")
    if has_tempo_changes(mid):
        print("ADVERTENCIA: el MIDI contiene cambios de tempo.")
        print("El archivo Strudel usa el tempo activo al comenzar la primera nota.")


if __name__ == "__main__":
    main()
