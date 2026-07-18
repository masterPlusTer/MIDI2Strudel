"""Simple experimental MIDI to Strudel converter.

Usage:
    python midi_to_strudel.py
    python midi_to_strudel.py song.mid

When no MIDI file is given, the script uses the first .mid or .midi file found
next to this script. The generated Strudel code is written to output/.
"""

from __future__ import annotations

import sys
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

import mido

# Easy settings. Change these if needed.
QUANTIZATION = 16  # 8, 16 or 32
SYNTH = "piano"
TRACK = None  # None = automatically choose the track with the most notes

NOTE_NAMES = ["c", "cs", "d", "ds", "e", "f", "fs", "g", "gs", "a", "as", "b"]


@dataclass(frozen=True)
class NoteEvent:
    start: float
    duration: float
    note: int
    velocity: int

    @property
    def end(self) -> float:
        return self.start + self.duration


def find_midi_file() -> Path:
    if len(sys.argv) > 1:
        path = Path(sys.argv[1]).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            raise SystemExit(f"No se encontró el archivo: {path}")
        return path

    folder = Path(__file__).resolve().parent
    files = sorted(list(folder.glob("*.mid")) + list(folder.glob("*.midi")))
    if not files:
        raise SystemExit(
            "No encontré ningún archivo .mid junto a midi_to_strudel.py.\n"
            "Copia un MIDI en esta carpeta y vuelve a ejecutar el script."
        )
    return files[0]


def count_notes(track: mido.MidiTrack) -> int:
    return sum(1 for msg in track if msg.type == "note_on" and msg.velocity > 0)


def choose_track(mid: mido.MidiFile) -> int:
    if TRACK is not None:
        if not 0 <= TRACK < len(mid.tracks):
            raise SystemExit(f"TRACK={TRACK} no existe. El MIDI tiene {len(mid.tracks)} pistas.")
        return TRACK

    counts = [count_notes(track) for track in mid.tracks]
    if not counts or max(counts) == 0:
        raise SystemExit("El MIDI no contiene notas utilizables.")
    return max(range(len(counts)), key=counts.__getitem__)


def first_bpm(mid: mido.MidiFile) -> float:
    tempo = 500_000
    for msg in mido.merge_tracks(mid.tracks):
        if msg.type == "set_tempo":
            tempo = msg.tempo
            break
    return float(mido.tempo2bpm(tempo))


def extract_notes(mid: mido.MidiFile, track_index: int) -> list[NoteEvent]:
    active: dict[tuple[int, int], deque[tuple[int, int]]] = defaultdict(deque)
    notes: list[NoteEvent] = []
    tick = 0

    for msg in mid.tracks[track_index]:
        tick += msg.time

        if msg.type == "note_on" and msg.velocity > 0:
            active[(msg.channel, msg.note)].append((tick, msg.velocity))
            continue

        is_note_end = msg.type == "note_off" or (
            msg.type == "note_on" and msg.velocity == 0
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

    return sorted(notes, key=lambda event: (event.start, event.note))


def quantize(notes: list[NoteEvent]) -> list[NoteEvent]:
    steps_per_beat = QUANTIZATION / 4
    result = []

    for event in notes:
        start_steps = round(event.start * steps_per_beat)
        duration_steps = max(1, round(event.duration * steps_per_beat))
        result.append(
            NoteEvent(
                start=start_steps / steps_per_beat,
                duration=duration_steps / steps_per_beat,
                note=event.note,
                velocity=event.velocity,
            )
        )

    return sorted(result, key=lambda event: (event.start, event.note))


def separate_voices(notes: list[NoteEvent]) -> list[list[NoteEvent]]:
    """Place overlapping notes into separate monophonic Strudel patterns."""
    voices: list[list[NoteEvent]] = []
    voice_ends: list[float] = []

    for event in sorted(notes, key=lambda item: (item.start, -item.duration, item.note)):
        for index, end in enumerate(voice_ends):
            if event.start >= end - 1e-9:
                voices[index].append(event)
                voice_ends[index] = event.end
                break
        else:
            voices.append([event])
            voice_ends.append(event.end)

    return voices


def note_name(number: int) -> str:
    return f"{NOTE_NAMES[number % 12]}{number // 12 - 1}"


def render_voice(notes: list[NoteEvent]) -> str:
    steps_per_beat = QUANTIZATION / 4
    cursor = 0
    tokens: list[str] = []

    for event in notes:
        start = round(event.start * steps_per_beat)
        duration = max(1, round(event.duration * steps_per_beat))
        gap = start - cursor

        if gap > 0:
            tokens.append("~" if gap == 1 else f"~@{gap}")

        token = note_name(event.note)
        if duration > 1:
            token += f"@{duration}"
        tokens.append(token)
        cursor = start + duration

    return f'note("{" ".join(tokens)}").s("{SYNTH}")'


def render_strudel(voices: list[list[NoteEvent]], bpm: float, source: Path, track: int) -> str:
    patterns = [render_voice(voice) for voice in voices if voice]
    if not patterns:
        raise SystemExit("No se pudo generar ningún patrón.")

    body = patterns[0]
    if len(patterns) > 1:
        body = "stack(\n  " + ",\n  ".join(patterns) + "\n)"

    return (
        "// Generated by midi_to_strudel.py\n"
        f"// Source: {source.name}\n"
        f"// Track: {track}\n"
        f"// BPM: {bpm:.2f}\n"
        f"// Quantization: 1/{QUANTIZATION}\n"
        f"// Voices: {len(patterns)}\n\n"
        f"setcpm({bpm / 4:.6g})\n\n"
        f"{body}\n"
    )


def main() -> None:
    midi_path = find_midi_file()
    mid = mido.MidiFile(midi_path)
    track_index = choose_track(mid)
    bpm = first_bpm(mid)

    notes = quantize(extract_notes(mid, track_index))
    if not notes:
        raise SystemExit(f"La pista {track_index} no contiene notas convertibles.")

    voices = separate_voices(notes)
    code = render_strudel(voices, bpm, midi_path, track_index)

    output_dir = Path(__file__).resolve().parent / "output"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / f"{midi_path.stem}.strudel"
    output_path.write_text(code, encoding="utf-8")

    print(f"MIDI: {midi_path.name}")
    print(f"Pista elegida: {track_index} ({len(notes)} notas)")
    print(f"Voces generadas: {len(voices)}")
    print(f"Resultado: {output_path}")


if __name__ == "__main__":
    main()
