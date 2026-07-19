from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

from mido import MidiFile, MidiTrack, MetaMessage


MIDI_EXTENSIONS = {".mid", ".midi"}


GENERAL_MIDI_INSTRUMENTS = [
    "Acoustic Grand Piano",
    "Bright Acoustic Piano",
    "Electric Grand Piano",
    "Honky-tonk Piano",
    "Electric Piano 1",
    "Electric Piano 2",
    "Harpsichord",
    "Clavinet",
    "Celesta",
    "Glockenspiel",
    "Music Box",
    "Vibraphone",
    "Marimba",
    "Xylophone",
    "Tubular Bells",
    "Dulcimer",
    "Drawbar Organ",
    "Percussive Organ",
    "Rock Organ",
    "Church Organ",
    "Reed Organ",
    "Accordion",
    "Harmonica",
    "Tango Accordion",
    "Acoustic Guitar (nylon)",
    "Acoustic Guitar (steel)",
    "Electric Guitar (jazz)",
    "Electric Guitar (clean)",
    "Electric Guitar (muted)",
    "Overdriven Guitar",
    "Distortion Guitar",
    "Guitar Harmonics",
    "Acoustic Bass",
    "Electric Bass (finger)",
    "Electric Bass (pick)",
    "Fretless Bass",
    "Slap Bass 1",
    "Slap Bass 2",
    "Synth Bass 1",
    "Synth Bass 2",
    "Violin",
    "Viola",
    "Cello",
    "Contrabass",
    "Tremolo Strings",
    "Pizzicato Strings",
    "Orchestral Harp",
    "Timpani",
    "String Ensemble 1",
    "String Ensemble 2",
    "Synth Strings 1",
    "Synth Strings 2",
    "Choir Aahs",
    "Voice Oohs",
    "Synth Voice",
    "Orchestra Hit",
    "Trumpet",
    "Trombone",
    "Tuba",
    "Muted Trumpet",
    "French Horn",
    "Brass Section",
    "Synth Brass 1",
    "Synth Brass 2",
    "Soprano Sax",
    "Alto Sax",
    "Tenor Sax",
    "Baritone Sax",
    "Oboe",
    "English Horn",
    "Bassoon",
    "Clarinet",
    "Piccolo",
    "Flute",
    "Recorder",
    "Pan Flute",
    "Blown Bottle",
    "Shakuhachi",
    "Whistle",
    "Ocarina",
    "Lead 1 (square)",
    "Lead 2 (sawtooth)",
    "Lead 3 (calliope)",
    "Lead 4 (chiff)",
    "Lead 5 (charang)",
    "Lead 6 (voice)",
    "Lead 7 (fifths)",
    "Lead 8 (bass + lead)",
    "Pad 1 (new age)",
    "Pad 2 (warm)",
    "Pad 3 (polysynth)",
    "Pad 4 (choir)",
    "Pad 5 (bowed)",
    "Pad 6 (metallic)",
    "Pad 7 (halo)",
    "Pad 8 (sweep)",
    "FX 1 (rain)",
    "FX 2 (soundtrack)",
    "FX 3 (crystal)",
    "FX 4 (atmosphere)",
    "FX 5 (brightness)",
    "FX 6 (goblins)",
    "FX 7 (echoes)",
    "FX 8 (sci-fi)",
    "Sitar",
    "Banjo",
    "Shamisen",
    "Koto",
    "Kalimba",
    "Bag Pipe",
    "Fiddle",
    "Shanai",
    "Tinkle Bell",
    "Agogo",
    "Steel Drums",
    "Woodblock",
    "Taiko Drum",
    "Melodic Tom",
    "Synth Drum",
    "Reverse Cymbal",
    "Guitar Fret Noise",
    "Breath Noise",
    "Seashore",
    "Bird Tweet",
    "Telephone Ring",
    "Helicopter",
    "Applause",
    "Gunshot",
]


METADATA_MESSAGE_TYPES = {
    "sequence_number",
    "text",
    "copyright",
    "track_name",
    "instrument_name",
    "lyrics",
    "marker",
    "cue_marker",
    "device_name",
    "midi_channel_prefix",
    "midi_port",
    "end_of_track",
    "set_tempo",
    "smpte_offset",
    "time_signature",
    "key_signature",
    "sequencer_specific",
}


def sanitize_filename(filename: str) -> str:
    """Return a Windows-safe filename."""
    invalid_characters = '<>:"/\\|?*'

    for character in invalid_characters:
        filename = filename.replace(character, "_")

    filename = filename.strip().strip(".")

    return filename or "unnamed_track"


def calculate_sha256(file_path: Path) -> str:
    """Calculate the SHA-256 checksum of a file."""
    digest = hashlib.sha256()

    with file_path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)

    return digest.hexdigest()


def make_json_safe(value: Any) -> Any:
    """Convert Mido values into JSON-compatible values."""
    if isinstance(value, bytes):
        return {
            "encoding": "hex",
            "value": value.hex(),
        }

    if isinstance(value, bytearray):
        return {
            "encoding": "hex",
            "value": bytes(value).hex(),
        }

    if isinstance(value, tuple):
        return [make_json_safe(item) for item in value]

    if isinstance(value, list):
        return [make_json_safe(item) for item in value]

    if isinstance(value, dict):
        return {
            str(key): make_json_safe(item)
            for key, item in value.items()
        }

    return value


def message_to_dictionary(
    message,
    message_index: int,
    absolute_ticks: int,
) -> dict[str, Any]:
    """
    Document every available field from one Mido message.
    """
    message_data = message.dict()

    return {
        "message_index": message_index,
        "delta_ticks": message.time,
        "absolute_ticks": absolute_ticks,
        "type": message.type,
        "is_meta": message.is_meta,
        "is_realtime": getattr(message, "is_realtime", False),
        "fields": make_json_safe(message_data),
        "mido_representation": str(message),
        "raw_bytes_when_available": get_message_bytes(message),
    }


def get_message_bytes(message) -> dict[str, Any] | None:
    """
    Return the encoded bytes for messages that Mido can encode directly.

    Meta messages and some system messages may not expose a simple
    standalone byte representation.
    """
    try:
        encoded = bytes(message.bytes())

        return {
            "decimal": list(encoded),
            "hex": encoded.hex(" "),
        }

    except Exception as error:
        return {
            "available": False,
            "reason": f"{type(error).__name__}: {error}",
        }


def find_messages(track, message_type: str):
    """Yield all messages of a requested type."""
    for message in track:
        if message.type == message_type:
            yield message


def get_text_values(track, message_type: str) -> list[str]:
    """Return all non-empty text values for one metadata type."""
    values = []

    for message in find_messages(track, message_type):
        name = getattr(message, "name", None)
        text = getattr(message, "text", None)

        value = name if name is not None else text

        if value is not None:
            value = str(value).strip()

            if value:
                values.append(value)

    return values


def get_track_names(track) -> list[str]:
    """Return every stored track_name value."""
    return get_text_values(track, "track_name")


def get_instrument_names(track) -> list[str]:
    """Return every stored instrument_name value."""
    return get_text_values(track, "instrument_name")


def get_program_changes(track) -> list[dict[str, int]]:
    """Return every MIDI program change with channel information."""
    programs = []

    for message in track:
        if message.type == "program_change":
            programs.append(
                {
                    "channel_zero_based": message.channel,
                    "channel_one_based": message.channel + 1,
                    "program_zero_based": message.program,
                    "program_one_based": message.program + 1,
                }
            )

    return programs


def get_bank_changes(track) -> list[dict[str, int]]:
    """
    Return Bank Select MSB and LSB controller messages.

    Controller 0 is Bank Select MSB.
    Controller 32 is Bank Select LSB.
    """
    bank_changes = []

    for message in track:
        if (
            message.type == "control_change"
            and message.control in {0, 32}
        ):
            bank_changes.append(
                {
                    "channel_zero_based": message.channel,
                    "channel_one_based": message.channel + 1,
                    "controller": message.control,
                    "bank_component": (
                        "MSB" if message.control == 0 else "LSB"
                    ),
                    "value": message.value,
                }
            )

    return bank_changes


def get_channels(track) -> list[int]:
    """Return every MIDI channel used by a track, one-based."""
    channels = {
        message.channel + 1
        for message in track
        if hasattr(message, "channel")
    }

    return sorted(channels)


def get_general_midi_name(program: int | None) -> str | None:
    """
    Return a General MIDI Level 1 name for a zero-based program.

    This is an interpretation, not necessarily stored text.
    """
    if program is None:
        return None

    if 0 <= program < len(GENERAL_MIDI_INSTRUMENTS):
        return GENERAL_MIDI_INSTRUMENTS[program]

    return None


def determine_documented_track_name(
    track,
    track_number: int,
) -> tuple[str, str]:
    """
    Determine the best track name and document its source.

    No inferred name is presented as if it were original metadata.
    """
    track_names = get_track_names(track)

    if track_names:
        return track_names[0], "original track_name meta event"

    instrument_names = get_instrument_names(track)

    if instrument_names:
        return (
            instrument_names[0],
            "original instrument_name meta event",
        )

    channels = get_channels(track)

    if 10 in channels:
        return "Percussion", "inferred from MIDI channel 10"

    program_changes = get_program_changes(track)

    if program_changes:
        first_program = program_changes[0]["program_zero_based"]
        general_midi_name = get_general_midi_name(first_program)

        if general_midi_name:
            return (
                general_midi_name,
                (
                    "inferred from first program_change using the "
                    "General MIDI Level 1 program table"
                ),
            )

    return (
        f"Track {track_number:02d}",
        "generated fallback because no name or program was available",
    )


def is_metadata_only_track(track) -> bool:
    """
    Return True when a track contains no channel or SysEx events.

    Such tracks are copied into every separated MIDI because they may
    contain tempo maps, markers, lyrics, names or sequencer metadata.
    """
    for message in track:
        if not message.is_meta:
            return False

    return True


def copy_track_exactly(track) -> MidiTrack:
    """
    Copy every parsed message without filtering or reordering it.
    """
    copied_track = MidiTrack()

    for message in track:
        copied_track.append(message.copy())

    return copied_track


def copy_track_with_documented_name(
    track,
    final_name: str,
) -> MidiTrack:
    """
    Copy every parsed message.

    Add a track_name only when the source track contains no valid
    track_name. Existing track_name events are never replaced.
    """
    copied_track = MidiTrack()
    original_names = get_track_names(track)

    if not original_names:
        copied_track.append(
            MetaMessage(
                "track_name",
                name=final_name,
                time=0,
            )
        )

    for message in track:
        copied_track.append(message.copy())

    return copied_track


def create_output_midi(source_midi: MidiFile) -> MidiFile:
    """Create a MIDI container with the original timing division."""
    return MidiFile(
        type=1,
        ticks_per_beat=source_midi.ticks_per_beat,
        charset=source_midi.charset,
        clip=source_midi.clip,
        debug=source_midi.debug,
    )


def build_track_report(
    track,
    track_index: int,
) -> dict[str, Any]:
    """Create a complete structured report for one track."""
    absolute_ticks = 0
    documented_messages = []
    message_type_counts = Counter()

    for message_index, message in enumerate(track):
        absolute_ticks += message.time
        message_type_counts[message.type] += 1

        documented_messages.append(
            message_to_dictionary(
                message=message,
                message_index=message_index,
                absolute_ticks=absolute_ticks,
            )
        )

    final_name, name_source = determine_documented_track_name(
        track,
        track_index + 1,
    )

    return {
        "track_index_zero_based": track_index,
        "track_number_one_based": track_index + 1,
        "message_count": len(track),
        "duration_ticks": absolute_ticks,
        "metadata_only": is_metadata_only_track(track),
        "original_track_names": get_track_names(track),
        "original_instrument_names": get_instrument_names(track),
        "documented_output_name": final_name,
        "documented_output_name_source": name_source,
        "channels_one_based": get_channels(track),
        "program_changes": get_program_changes(track),
        "bank_select_messages": get_bank_changes(track),
        "message_type_counts": dict(
            sorted(message_type_counts.items())
        ),
        "messages": documented_messages,
    }


def write_text_report(
    report_path: Path,
    midi_report: dict[str, Any],
) -> None:
    """Write a human-readable report containing every parsed message."""
    with report_path.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as report:
        source = midi_report["source_file"]

        report.write("COMPLETE MIDI DOCUMENTATION\n")
        report.write("=" * 80 + "\n\n")

        report.write(f"Source filename: {source['name']}\n")
        report.write(f"Source size: {source['size_bytes']} bytes\n")
        report.write(f"Source SHA-256: {source['sha256']}\n")
        report.write(f"MIDI type: {midi_report['midi']['type']}\n")
        report.write(
            "Ticks per beat: "
            f"{midi_report['midi']['ticks_per_beat']}\n"
        )
        report.write(
            f"Track count: {midi_report['midi']['track_count']}\n"
        )
        report.write(
            f"Length in seconds: "
            f"{midi_report['midi']['length_seconds']}\n"
        )
        report.write("\n")

        for track in midi_report["tracks"]:
            report.write("=" * 80 + "\n")
            report.write(
                f"TRACK {track['track_number_one_based']:02d}\n"
            )
            report.write("=" * 80 + "\n")

            report.write(
                "Original track names: "
                f"{track['original_track_names'] or '(none stored)'}\n"
            )
            report.write(
                "Original instrument names: "
                f"{track['original_instrument_names'] or '(none stored)'}\n"
            )
            report.write(
                "Documented output name: "
                f"{track['documented_output_name']}\n"
            )
            report.write(
                "Name source: "
                f"{track['documented_output_name_source']}\n"
            )
            report.write(
                f"Metadata-only track: {track['metadata_only']}\n"
            )
            report.write(
                f"Channels: {track['channels_one_based'] or '(none)'}\n"
            )
            report.write(
                f"Program changes: {track['program_changes'] or '(none)'}\n"
            )
            report.write(
                "Bank Select messages: "
                f"{track['bank_select_messages'] or '(none)'}\n"
            )
            report.write(
                f"Message count: {track['message_count']}\n"
            )
            report.write(
                f"Duration in ticks: {track['duration_ticks']}\n"
            )
            report.write(
                "Message type counts: "
                f"{track['message_type_counts']}\n"
            )
            report.write("\n")

            for message in track["messages"]:
                report.write(
                    f"[{message['message_index']:06d}] "
                    f"delta={message['delta_ticks']} "
                    f"absolute={message['absolute_ticks']} "
                    f"type={message['type']} "
                    f"meta={message['is_meta']}\n"
                )

                report.write(
                    f"    Mido: {message['mido_representation']}\n"
                )

                report.write(
                    "    Fields: "
                    + json.dumps(
                        message["fields"],
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + "\n"
                )

                report.write(
                    "    Encoded bytes: "
                    + json.dumps(
                        message["raw_bytes_when_available"],
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + "\n"
                )

            report.write("\n")


def write_hex_dump(source_path: Path, output_path: Path) -> None:
    """Write a complete hexadecimal dump of the original MIDI file."""
    data = source_path.read_bytes()

    with output_path.open(
        "w",
        encoding="ascii",
        newline="\n",
    ) as output:
        for offset in range(0, len(data), 16):
            block = data[offset:offset + 16]

            hex_part = " ".join(
                f"{byte:02X}"
                for byte in block
            )

            ascii_part = "".join(
                chr(byte) if 32 <= byte <= 126 else "."
                for byte in block
            )

            output.write(
                f"{offset:08X}  "
                f"{hex_part:<47}  "
                f"{ascii_part}\n"
            )


def create_unique_filename(
    track_number: int,
    track_name: str,
    used_names: set[str],
) -> str:
    """Create a unique track filename."""
    safe_name = sanitize_filename(track_name)
    base_name = f"{track_number:02d}_{safe_name}"
    candidate = base_name
    duplicate_number = 2

    while candidate.lower() in used_names:
        candidate = f"{base_name}_{duplicate_number}"
        duplicate_number += 1

    used_names.add(candidate.lower())

    return f"{candidate}.mid"


def split_midi_file(midi_path: Path) -> None:
    """
    Split one MIDI and produce exhaustive documentation.
    """
    source_midi = MidiFile(
        midi_path,
        clip=False,
    )

    output_directory = (
        midi_path.parent
        / f"{midi_path.stem}_complete_split"
    )

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    original_directory = output_directory / "original"
    separated_directory = output_directory / "separated_tracks"
    documentation_directory = output_directory / "documentation"

    original_directory.mkdir(exist_ok=True)
    separated_directory.mkdir(exist_ok=True)
    documentation_directory.mkdir(exist_ok=True)

    original_copy_path = original_directory / midi_path.name
    shutil.copy2(midi_path, original_copy_path)

    original_sha256 = calculate_sha256(midi_path)
    copied_sha256 = calculate_sha256(original_copy_path)

    if original_sha256 != copied_sha256:
        raise RuntimeError(
            "The preserved original copy failed SHA-256 verification."
        )

    track_reports = [
        build_track_report(track, track_index)
        for track_index, track in enumerate(source_midi.tracks)
    ]

    midi_report = {
        "documentation_notes": {
            "preservation_scope": (
                "Every message parsed by Mido is documented. "
                "The complete original file is also preserved byte for byte."
            ),
            "generated_track_names": (
                "Generated names are explicitly marked as inferred or "
                "generated and are never reported as original metadata."
            ),
            "byte_level_limit": (
                "Separated MIDI files cannot be byte-identical to the "
                "original because their track structure is different. "
                "The original copy and hexadecimal dump preserve all "
                "original bytes."
            ),
        },
        "source_file": {
            "name": midi_path.name,
            "absolute_path": str(midi_path.resolve()),
            "size_bytes": midi_path.stat().st_size,
            "sha256": original_sha256,
            "preserved_copy": str(original_copy_path.resolve()),
            "preserved_copy_sha256": copied_sha256,
            "copy_verified_identical": True,
        },
        "midi": {
            "type": source_midi.type,
            "ticks_per_beat": source_midi.ticks_per_beat,
            "track_count": len(source_midi.tracks),
            "length_seconds": source_midi.length,
            "charset": source_midi.charset,
            "clip": source_midi.clip,
        },
        "tracks": track_reports,
        "separated_files": [],
    }

    metadata_track_indexes = [
        index
        for index, track in enumerate(source_midi.tracks)
        if is_metadata_only_track(track)
    ]

    used_names: set[str] = set()

    for track_index, source_track in enumerate(source_midi.tracks):
        track_number = track_index + 1
        track_report = track_reports[track_index]

        documented_name = track_report["documented_output_name"]

        output_filename = create_unique_filename(
            track_number,
            documented_name,
            used_names,
        )

        output_path = separated_directory / output_filename
        output_midi = create_output_midi(source_midi)

        copied_metadata_indexes = []

        # Copy every metadata-only track into every separated file.
        for metadata_index in metadata_track_indexes:
            if metadata_index == track_index:
                continue

            output_midi.tracks.append(
                copy_track_exactly(
                    source_midi.tracks[metadata_index]
                )
            )

            copied_metadata_indexes.append(metadata_index)

        selected_track = copy_track_with_documented_name(
            source_track,
            documented_name,
        )

        output_midi.tracks.append(selected_track)
        output_midi.save(output_path)

        midi_report["separated_files"].append(
            {
                "source_track_index_zero_based": track_index,
                "source_track_number_one_based": track_number,
                "filename": output_filename,
                "path": str(output_path.resolve()),
                "sha256": calculate_sha256(output_path),
                "documented_track_name": documented_name,
                "documented_track_name_source": (
                    track_report["documented_output_name_source"]
                ),
                "metadata_track_indexes_copied": (
                    copied_metadata_indexes
                ),
                "all_selected_track_messages_copied": True,
            }
        )

        print(
            f"Track {track_number:02d}: "
            f"{documented_name} -> {output_filename}"
        )

    json_report_path = (
        documentation_directory
        / f"{midi_path.stem}_complete_report.json"
    )

    text_report_path = (
        documentation_directory
        / f"{midi_path.stem}_complete_report.txt"
    )

    hex_dump_path = (
        documentation_directory
        / f"{midi_path.stem}_original_hex_dump.txt"
    )

    with json_report_path.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as json_file:
        json.dump(
            midi_report,
            json_file,
            ensure_ascii=False,
            indent=2,
            sort_keys=False,
        )

    write_text_report(
        text_report_path,
        midi_report,
    )

    write_hex_dump(
        midi_path,
        hex_dump_path,
    )

    print()
    print(f"Finished: {midi_path.name}")
    print(f"Original SHA-256: {original_sha256}")
    print(f"Verified original copy: {original_copy_path}")
    print(f"JSON report: {json_report_path}")
    print(f"Text report: {text_report_path}")
    print(f"Hex dump: {hex_dump_path}")
    print()


def find_midi_files(script_directory: Path) -> list[Path]:
    """Find every MIDI located directly beside the script."""
    return sorted(
        (
            path
            for path in script_directory.iterdir()
            if (
                path.is_file()
                and path.suffix.lower() in MIDI_EXTENSIONS
            )
        ),
        key=lambda path: path.name.lower(),
    )


def main() -> None:
    script_directory = Path(__file__).resolve().parent
    midi_files = find_midi_files(script_directory)

    if not midi_files:
        print("No MIDI files were found.")
        print(
            "Place one or more .mid or .midi files "
            "in the same directory as this script."
        )
        input("Press Enter to close...")
        return

    print(f"MIDI files found: {len(midi_files)}")
    print()

    successful_files = 0
    failed_files = 0

    for midi_path in midi_files:
        try:
            print("=" * 80)
            print(f"Processing: {midi_path.name}")
            print("=" * 80)

            split_midi_file(midi_path)
            successful_files += 1

        except Exception as error:
            failed_files += 1

            print()
            print(f"Could not process: {midi_path.name}")
            print(f"Error type: {type(error).__name__}")
            print(f"Error details: {error}")
            print()

    print("=" * 80)
    print("PROCESSING COMPLETE")
    print(f"Successful MIDI files: {successful_files}")
    print(f"Failed MIDI files: {failed_files}")
    print("=" * 80)

    input("Press Enter to close...")


if __name__ == "__main__":
    main()
    
