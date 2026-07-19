"""Experimental expressive multi-track MIDI to Strudel converter.

Given one complete MIDI file, this script automatically:

1. Finds every MIDI track containing notes.
2. Writes one normalized .strudel file per track.
3. Writes one synchronized combined .strudel arrangement.

It retains note velocity, sustain pedal (CC64), channel volume (CC7),
expression (CC11), pan (CC10), program changes, and uses finer 1/32 timing.
The current renderer deliberately uses a known-working piano sample for
melodic tracks. General MIDI program numbers are retained in the extracted
data but are not yet mapped to samples, because unavailable sample names can
make an otherwise valid Strudel file silent.

Usage:
    python midi_to_strudel_multitrack_expressive.py song.mid
"""

from __future__ import annotations

import math
import re
import sys
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

import mido


QUANTIZATION = 32
DEFAULT_SOUND = "piano"
ROOM = 0.08
RELEASE = 0.05
CLIP = 0.78
NORMALIZE_INDIVIDUAL_TRACKS = True
MAX_VOICES_PER_TRACK = 8

NOTE_NAMES = (
    "c", "c#", "d", "d#", "e", "f",
    "f#", "g", "g#", "a", "a#", "b",
)

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
    program: int
    volume: int
    expression: int
    pan: int

    @property
    def end(self) -> float:
        return self.start + self.duration

    @property
    def is_drum(self) -> bool:
        return self.channel == 9


@dataclass(frozen=True)
class ActiveNote:
    start_tick: int
    velocity: int
    program: int
    volume: int
    expression: int
    pan: int


@dataclass(frozen=True)
class ReleasedNote:
    note: int
    active: ActiveNote


@dataclass(frozen=True)
class Segment:
    symbol: str
    length: int
    gain: float
    pan: float


@dataclass
class ConvertedTrack:
    index: int
    name: str
    notes: list[NoteEvent]
    melodic_voices: list[list[NoteEvent]]
    drum_voices: list[list[NoteEvent]]


# ---------------------------------------------------------------------------
# MIDI discovery and metadata
# ---------------------------------------------------------------------------


def find_midi_file() -> Path:
    if len(sys.argv) > 1:
        path = Path(sys.argv[1]).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        path = path.resolve()
        if not path.exists():
            raise SystemExit(f"No se encontro el archivo: {path}")
        if path.suffix.lower() not in {".mid", ".midi"}:
            raise SystemExit(f"El archivo no parece ser MIDI: {path}")
        return path

    folder = Path(__file__).resolve().parent
    files = sorted([*folder.glob("*.mid"), *folder.glob("*.midi")])
    if not files:
        raise SystemExit("No encontre ningun archivo .mid o .midi junto al script.")
    return files[0]


def absolute_messages(mid: mido.MidiFile):
    absolute_tick = 0
    for message in mido.merge_tracks(mid.tracks):
        absolute_tick += message.time
        yield absolute_tick, message


def tempo_at_first_note(mid: mido.MidiFile) -> int:
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


def safe_name(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", text.strip()).strip("_")
    return cleaned or "track"


# ---------------------------------------------------------------------------
# Expressive extraction
# ---------------------------------------------------------------------------


def extract_notes(mid: mido.MidiFile, track_index: int) -> list[NoteEvent]:
    active: dict[tuple[int, int], deque[ActiveNote]] = defaultdict(deque)
    sustained: dict[int, list[ReleasedNote]] = defaultdict(list)
    pedal_down: dict[int, bool] = defaultdict(bool)
    programs: dict[int, int] = defaultdict(int)
    volumes: dict[int, int] = defaultdict(lambda: 100)
    expressions: dict[int, int] = defaultdict(lambda: 127)
    pans: dict[int, int] = defaultdict(lambda: 64)
    notes: list[NoteEvent] = []
    tick = 0

    def close_note(channel: int, note_number: int,
                   item: ActiveNote, end_tick: int) -> None:
        if end_tick <= item.start_tick:
            return
        notes.append(NoteEvent(
            start=item.start_tick / mid.ticks_per_beat,
            duration=(end_tick - item.start_tick) / mid.ticks_per_beat,
            note=note_number,
            velocity=item.velocity,
            channel=channel,
            program=item.program,
            volume=item.volume,
            expression=item.expression,
            pan=item.pan,
        ))

    for message in mid.tracks[track_index]:
        tick += message.time

        if message.type == "program_change":
            programs[message.channel] = message.program
            continue

        if message.type == "control_change":
            channel = message.channel
            if message.control == 7:
                volumes[channel] = message.value
                continue
            if message.control == 10:
                pans[channel] = message.value
                continue
            if message.control == 11:
                expressions[channel] = message.value
                continue
            if message.control == 64:
                was_down = pedal_down[channel]
                is_down = message.value >= 64
                pedal_down[channel] = is_down
                if was_down and not is_down:
                    pending = sustained[channel]
                    sustained[channel] = []
                    for released in pending:
                        close_note(channel, released.note, released.active, tick)
                continue
            if message.control in {120, 121, 123}:
                for key in list(active):
                    key_channel, note_number = key
                    if key_channel != channel:
                        continue
                    while active[key]:
                        close_note(channel, note_number, active[key].popleft(), tick)
                for released in sustained[channel]:
                    close_note(channel, released.note, released.active, tick)
                sustained[channel] = []
                pedal_down[channel] = False
                if message.control == 121:
                    volumes[channel] = 100
                    expressions[channel] = 127
                    pans[channel] = 64
                continue

        if message.type == "note_on" and message.velocity > 0:
            active[(message.channel, message.note)].append(ActiveNote(
                start_tick=tick,
                velocity=message.velocity,
                program=programs[message.channel],
                volume=volumes[message.channel],
                expression=expressions[message.channel],
                pan=pans[message.channel],
            ))
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
        item = active[key].popleft()
        if pedal_down[message.channel] and message.channel != 9:
            sustained[message.channel].append(ReleasedNote(message.note, item))
        else:
            close_note(message.channel, message.note, item, tick)

    final_tick = tick
    for (channel, note_number), queue in active.items():
        while queue:
            close_note(channel, note_number, queue.popleft(), final_tick)
    for channel, pending in sustained.items():
        for released in pending:
            close_note(channel, released.note, released.active, final_tick)

    return sorted(notes, key=lambda e: (e.start, e.channel, e.note, e.duration))


# ---------------------------------------------------------------------------
# Timing and voices
# ---------------------------------------------------------------------------


def steps_per_beat() -> int:
    if QUANTIZATION % 4:
        raise SystemExit("QUANTIZATION debe ser divisible por 4.")
    return QUANTIZATION // 4


def copy_event(event: NoteEvent, *, start: float | None = None,
               duration: float | None = None) -> NoteEvent:
    return NoteEvent(
        start=event.start if start is None else start,
        duration=event.duration if duration is None else duration,
        note=event.note,
        velocity=event.velocity,
        channel=event.channel,
        program=event.program,
        volume=event.volume,
        expression=event.expression,
        pan=event.pan,
    )


def quantize(notes: list[NoteEvent]) -> list[NoteEvent]:
    grid = steps_per_beat()
    result: list[NoteEvent] = []
    for event in notes:
        start_step = round(event.start * grid)
        end_step = max(start_step + 1, round(event.end * grid))
        result.append(copy_event(
            event,
            start=start_step / grid,
            duration=(end_step - start_step) / grid,
        ))
    return sorted(result, key=lambda e: (e.start, e.channel, e.note, e.duration))


def shift_notes(notes: list[NoteEvent], offset: float) -> list[NoteEvent]:
    return [copy_event(event, start=max(0.0, event.start - offset)) for event in notes]


def normalize(notes: list[NoteEvent]) -> list[NoteEvent]:
    if not notes:
        return []
    return shift_notes(notes, min(event.start for event in notes))


def separate_voices(notes: list[NoteEvent], max_voices: int) -> list[list[NoteEvent]]:
    voices: list[list[NoteEvent]] = []
    ends: list[float] = []
    pitches: list[int] = []
    channels: list[int] = []

    for event in sorted(notes, key=lambda e: (e.start, -e.duration, e.channel, e.note)):
        available = [i for i, end in enumerate(ends) if event.start >= end - 1e-9]
        if available:
            best = min(available, key=lambda i: (
                channels[i] != event.channel,
                abs(event.note - pitches[i]),
                ends[i],
                i,
            ))
            voices[best].append(event)
            ends[best] = event.end
            pitches[best] = event.note
            channels[best] = event.channel
            continue

        if len(voices) < max_voices:
            voices.append([event])
            ends.append(event.end)
            pitches.append(event.note)
            channels.append(event.channel)
            continue

        # Deliberately drop excess simultaneous notes. It is less faithful,
        # but preferable to eventually killing the browser audio context.

    return voices


def prepare_track(index: int, name: str,
                  notes: list[NoteEvent]) -> ConvertedTrack:
    melodic = [event for event in notes if not event.is_drum]
    drums = [event for event in notes if event.is_drum]
    return ConvertedTrack(
        index=index,
        name=name,
        notes=notes,
        melodic_voices=separate_voices(melodic, MAX_VOICES_PER_TRACK),
        drum_voices=separate_voices(drums, 4),
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def note_name(number: int) -> str:
    return f"{NOTE_NAMES[number % 12]}{number // 12 - 1}"


def expressive_gain(event: NoteEvent) -> float:
    velocity = max(1, min(127, event.velocity)) / 127
    volume = max(0, min(127, event.volume)) / 127
    expression = max(0, min(127, event.expression)) / 127
    return max(0.035, min(1.0, velocity ** 1.45 * volume * expression))


def expressive_pan(event: NoteEvent) -> float:
    return max(0.0, min(1.0, event.pan / 127))


def format_number(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text if text else "0"


def weighted(symbol: str, length: int) -> str:
    return symbol if length <= 1 else f"{symbol}@{length}"


def append_segment(segments: list[Segment], segment: Segment) -> None:
    if segment.length <= 0:
        return
    if segments and segment.symbol == "~" and segments[-1].symbol == "~":
        old = segments[-1]
        segments[-1] = Segment("~", old.length + segment.length, 0.0, 0.5)
    else:
        segments.append(segment)


def render_bar_segments(notes: list[NoteEvent], bar_start: float,
                        bar_length: float, drum: bool) -> list[Segment]:
    grid = steps_per_beat()
    bar_steps = round(bar_length * grid)
    bar_end = bar_start + bar_length
    segments: list[Segment] = []
    cursor = 0

    relevant = [
        event for event in notes
        if event.end > bar_start + 1e-9 and event.start < bar_end - 1e-9
    ]

    for event in relevant:
        start_step = round((max(event.start, bar_start) - bar_start) * grid)
        end_step = round((min(event.end, bar_end) - bar_start) * grid)
        start_step = max(cursor, max(0, min(bar_steps, start_step)))
        end_step = max(0, min(bar_steps, end_step))
        if end_step <= start_step:
            continue

        append_segment(segments, Segment("~", start_step - cursor, 0.0, 0.5))
        symbol = DRUM_MAP.get(event.note, "sd") if drum else note_name(event.note)
        append_segment(segments, Segment(
            symbol=symbol,
            length=end_step - start_step,
            gain=expressive_gain(event),
            pan=expressive_pan(event),
        ))
        cursor = end_step

    append_segment(segments, Segment("~", bar_steps - cursor, 0.0, 0.5))
    return segments or [Segment("~", bar_steps, 0.0, 0.5)]


def parameter_symbol(segment: Segment, field: str) -> str:
    if segment.symbol == "~":
        return "~"
    if field == "note":
        return segment.symbol
    if field == "gain":
        return format_number(segment.gain)
    if field == "pan":
        return format_number(segment.pan)
    raise ValueError(field)


def render_parameter_bar(segments: list[Segment], field: str,
                         bar_steps: int) -> str:
    if len(segments) == 1 and segments[0].length == bar_steps:
        return parameter_symbol(segments[0], field)
    return " ".join(weighted(parameter_symbol(segment, field), segment.length)
                    for segment in segments)


def total_bars(notes: list[NoteEvent], bar_length: float) -> int:
    if not notes:
        return 1
    return max(1, math.ceil(max(event.end for event in notes) / bar_length))


def render_voice(variable: str, notes: list[NoteEvent], bars: int,
                 bar_length: float, drum: bool) -> str:
    bar_steps = round(bar_length * steps_per_beat())
    rendered_bars: list[str] = []

    for bar_index in range(bars):
        segments = render_bar_segments(
            notes,
            bar_index * bar_length,
            bar_length,
            drum,
        )
        note_bar = render_parameter_bar(segments, "note", bar_steps)
        gain_bar = render_parameter_bar(segments, "gain", bar_steps)
        pan_bar = render_parameter_bar(segments, "pan", bar_steps)
        comma = "," if bar_index < bars - 1 else ""
        source = "s" if drum else "note"
        sound = "" if drum else f'.s("{DEFAULT_SOUND}")'
        rendered_bars.append(
            f'  {source}("{note_bar}")'
            f'{sound}'
            f'.gain("{gain_bar}")'
            f'.pan("{pan_bar}")'
            f'.clip({0.42 if drum else CLIP})'
            f'{comma} // bar {bar_index + 1}'
        )

    effects = "" if drum else f".release({RELEASE}).room({ROOM})"
    return (
        f"const {variable} = cat(\n"
        + "\n".join(rendered_bars)
        + f"\n){effects}"
    )


def render_track_patterns(track: ConvertedTrack, bars: int,
                          bar_length: float, prefix: str) -> tuple[list[str], list[str]]:
    definitions: list[str] = [f"// Track {track.index}: {track.name}"]
    names: list[str] = []

    for voice_index, voice in enumerate(track.melodic_voices, start=1):
        name = f"{prefix}_voice{voice_index}"
        definitions.append(render_voice(name, voice, bars, bar_length, False))
        names.append(name)

    for voice_index, voice in enumerate(track.drum_voices, start=1):
        name = f"{prefix}_drums{voice_index}"
        definitions.append(render_voice(name, voice, bars, bar_length, True))
        names.append(name)

    return definitions, names


def stack_body(names: list[str], master_gain: float) -> str:
    if not names:
        return "silence"
    if len(names) == 1:
        return f"{names[0]}.gain({master_gain:.4f})"
    return (
        "stack(\n  "
        + ",\n  ".join(names)
        + f"\n).gain({master_gain:.4f})"
    )


def render_individual(track: ConvertedTrack, bpm: float,
                      numerator: int, denominator: int,
                      source_name: str) -> str:
    notes = normalize(track.notes) if NORMALIZE_INDIVIDUAL_TRACKS else track.notes
    prepared = prepare_track(track.index, track.name, notes)
    bar_length = numerator * 4 / denominator
    bars = total_bars(notes, bar_length)
    definitions, names = render_track_patterns(
        prepared, bars, bar_length, f"track{track.index}"
    )
    master_gain = min(0.72, 1.15 / math.sqrt(max(1, len(names))))
    cpm = bpm / bar_length
    return (
        "// Generated by midi_to_strudel_multitrack_expressive.py\n"
        f"// Source: {source_name}\n"
        f"// MIDI track: {track.index} - {track.name}\n"
        f"// BPM: {bpm:.2f}\n"
        f"// Time signature: {numerator}/{denominator}\n"
        f"// Quantization: 1/{QUANTIZATION}\n"
        f"// Voices: {len(names)}\n"
        f"// Start normalized: {'yes' if NORMALIZE_INDIVIDUAL_TRACKS else 'no'}\n"
        "// Retains velocity, CC7, CC10, CC11 and CC64.\n\n"
        f"setcpm({cpm:.8g})\n\n"
        + "\n\n".join(definitions)
        + "\n\n"
        + stack_body(names, master_gain)
        + "\n"
    )


def render_combined(tracks: list[ConvertedTrack], bpm: float,
                    numerator: int, denominator: int,
                    source_name: str) -> str:
    all_notes = [event for track in tracks for event in track.notes]
    if not all_notes:
        raise SystemExit("No hay notas para combinar.")

    global_start = min(event.start for event in all_notes)
    shifted_tracks = [
        prepare_track(track.index, track.name, shift_notes(track.notes, global_start))
        for track in tracks
    ]
    shifted_notes = [event for track in shifted_tracks for event in track.notes]
    bar_length = numerator * 4 / denominator
    bars = total_bars(shifted_notes, bar_length)

    definitions: list[str] = []
    names: list[str] = []
    for track in shifted_tracks:
        track_definitions, track_names = render_track_patterns(
            track, bars, bar_length, f"track{track.index}"
        )
        definitions.extend(track_definitions)
        names.extend(track_names)

    # Conservative global gain prevents dense arrangements from clipping.
    master_gain = min(0.42, 0.92 / math.sqrt(max(1, len(names))))
    cpm = bpm / bar_length
    return (
        "// Generated by midi_to_strudel_multitrack_expressive.py\n"
        f"// Source: {source_name}\n"
        f"// BPM: {bpm:.2f}\n"
        f"// Time signature: {numerator}/{denominator}\n"
        f"// Quantization: 1/{QUANTIZATION}\n"
        f"// MIDI tracks: {len(tracks)}\n"
        f"// Patterns stacked: {len(names)}\n"
        f"// Maximum melodic voices per track: {MAX_VOICES_PER_TRACK}\n"
        f"// Removed global leading silence: {global_start:.4f} beats\n"
        "// Retains velocity, CC7, CC10, CC11 and CC64.\n"
        "// Program changes are read but melodic tracks use the stable piano sample.\n\n"
        f"setcpm({cpm:.8g})\n\n"
        + "\n\n".join(definitions)
        + "\n\n"
        + stack_body(names, master_gain)
        + "\n"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    midi_path = find_midi_file()
    try:
        mid = mido.MidiFile(midi_path)
    except (OSError, EOFError, ValueError) as exc:
        raise SystemExit(f"No se pudo leer el MIDI:\n{exc}") from exc

    tempo = tempo_at_first_note(mid)
    bpm = float(mido.tempo2bpm(tempo))
    numerator, denominator = first_time_signature(mid)

    tracks: list[ConvertedTrack] = []
    for index, midi_track in enumerate(mid.tracks):
        raw_notes = extract_notes(mid, index)
        if not raw_notes:
            continue
        notes = quantize(raw_notes)
        tracks.append(prepare_track(index, get_track_name(midi_track, index), notes))

    if not tracks:
        raise SystemExit("El MIDI no contiene pistas con notas convertibles.")

    output_dir = Path(__file__).resolve().parent / "output" / safe_name(midi_path.stem)
    output_dir.mkdir(parents=True, exist_ok=True)

    for track in tracks:
        filename = (
            f"{safe_name(midi_path.stem)}_track_{track.index:02d}_"
            f"{safe_name(track.name)}_expressive.strudel"
        )
        path = output_dir / filename
        path.write_text(
            render_individual(track, bpm, numerator, denominator, midi_path.name),
            encoding="utf-8",
        )
        print(f"Pista {track.index}: {track.name} -> {path.name}")

    combined_path = output_dir / f"{safe_name(midi_path.stem)}_combined_expressive.strudel"
    combined_path.write_text(
        render_combined(tracks, bpm, numerator, denominator, midi_path.name),
        encoding="utf-8",
    )

    print()
    print(f"MIDI: {midi_path.name}")
    print(f"Pistas convertidas: {len(tracks)}")
    print(f"BPM usado: {bpm:.2f}")
    print(f"Compas: {numerator}/{denominator}")
    print(f"Cuantizacion: 1/{QUANTIZATION}")
    if has_tempo_changes(mid):
        print("Aviso: el MIDI contiene cambios de tempo; se usa el tempo de la primera nota.")
    print(f"Carpeta de salida: {output_dir}")
    print(f"Combinado: {combined_path.name}")


if __name__ == "__main__":
    main()
