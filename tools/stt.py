r"""
음성 인식(STT, Speech-to-Text) 기능 구현
    - WhisperX로 음성인식 하므로 별도의 API는 필요없다
    - 자막변환 기능 : SRT, VTT, LRC
"""

import argparse
import difflib
import importlib
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path


class SttError(Exception):
    """사용자에게 안내할 수 있는 음성 인식 오류."""


PRICE_PER_MINUTE_USD = {"google": 0.016, "openai": 0.006}
USD_TO_KRW = 1500
GOOGLE_REGION = "us"
WHISPERX_EXECUTABLE = Path(r"C:\Python\venv\whisperx\Scripts\whisperx.exe")
AUDIO_SEPARATOR_EXECUTABLE = Path(r"C:\Python\venv\whisperx\Scripts\audio-separator.exe")
AUDIO_SEPARATOR_MODEL = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
AUDIO_SEPARATOR_MODEL_DIR = AUDIO_SEPARATOR_EXECUTABLE.parents[1] / "audio-separator-models"
SUBTITLE_TIMESTAMP_PATTERN = re.compile(
    r"^(?P<start>(?:[0-9]+:)?[0-9]{2}:[0-9]{2}[,.][0-9]{3})\s+-->\s+"
    r"(?P<end>(?:[0-9]+:)?[0-9]{2}:[0-9]{2}[,.][0-9]{3})(?:\s+(?P<settings>.*))?$"
)
LRC_TIMESTAMP_PATTERN = re.compile(
    r"\[(?P<minutes>[0-9]+):(?P<seconds>[0-5][0-9])(?:[.:](?P<fraction>[0-9]{1,3}))?\]"
)


def decode_subprocess_output(output):
    """외부 프로그램의 바이트 출력을 UTF-8 문자열로 안전하게 변환한다."""
    return output.decode("utf-8", errors="replace").strip()


def convert_to_audio_chunks(input_path, output_dir):
    """입력 미디어의 첫 오디오 트랙을 Google 제한보다 짧은 WAV 조각으로 변환한다."""
    if shutil.which("ffmpeg") is None:
        raise SttError("ffmpeg를 찾을 수 없습니다. ffmpeg를 설치하고 PATH에 추가하세요.")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_pattern = output_dir / "audio_%04d.wav"
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(input_path),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        "-f",
        "segment",
        "-segment_time",
        "55",
        "-reset_timestamps",
        "1",
        str(output_pattern),
    ]
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode != 0:
        detail = decode_subprocess_output(result.stderr) or "오디오 변환에 실패했습니다."
        raise SttError(f"ffmpeg 오류: {detail}")

    chunks = sorted(output_dir.glob("audio_*.wav"))
    if not chunks:
        raise SttError("입력 파일에서 오디오 트랙을 찾을 수 없습니다.")
    return chunks


def get_audio_durations(audio_paths):
    """ffprobe로 각 오디오 조각의 재생 시간을 초 단위로 구한다."""
    if shutil.which("ffprobe") is None:
        raise SttError("ffprobe를 찾을 수 없습니다. ffmpeg를 설치하고 PATH에 추가하세요.")

    durations = []
    for audio_path in audio_paths:
        command = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "format=duration:packet=pts_time,duration_time",
            "-of",
            "json",
            str(audio_path),
        ]
        result = subprocess.run(command, capture_output=True, check=False)
        if result.returncode != 0:
            detail = decode_subprocess_output(result.stderr) or "오디오 길이를 확인할 수 없습니다."
            raise SttError(f"ffprobe 오류: {detail}")
        try:
            metadata = json.loads(result.stdout)
            packets = [packet for packet in metadata.get("packets", []) if "pts_time" in packet]
            if packets:
                first_pts = min(float(packet["pts_time"]) for packet in packets)
                last_end = max(
                    float(packet["pts_time"]) + float(packet.get("duration_time", 0)) for packet in packets
                )
                duration = last_end - first_pts
            else:
                duration = metadata.get("format", {}).get("duration")
            durations.append(float(duration))
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise SttError(f"오디오 길이를 확인할 수 없습니다: {audio_path}") from error
    return durations


def format_usage(api, durations):
    """처리 사용량과 공개 단가 기준 예상 비용을 표시할 문자열로 만든다."""
    audio_seconds = sum(durations)
    billed_seconds = sum(math.ceil(duration) for duration in durations) if api == "google" else audio_seconds
    billed_minutes = billed_seconds / 60
    price_per_minute = PRICE_PER_MINUTE_USD[api]
    estimated_cost = billed_minutes * price_per_minute
    estimated_cost_krw = estimated_cost * USD_TO_KRW
    return (
        "\n--- 사용량 및 예상 비용 ---\n"
        f"API: {api}\n"
        f"오디오 길이: {audio_seconds:.2f}초 ({audio_seconds / 60:.2f}분)\n"
        f"청구 계산 시간: {billed_seconds:.2f}초 ({billed_minutes:.2f}분)\n"
        f"단가: ${price_per_minute:.3f}/분\n"
        f"예상 비용: ${estimated_cost:.6f} USD\n"
        f"원화 환산: {estimated_cost_krw:,.2f}원 (1 USD = {USD_TO_KRW:,}원)\n"
        "참고: 공개 단가 기준 추정치이며 무료 사용량, 할인 및 세금은 반영하지 않습니다."
    )


def save_transcript(input_path, transcript):
    """전사 결과를 입력 파일 옆의 중복되지 않는 UTF-8 텍스트 파일로 저장한다."""
    output_path = input_path.with_suffix(".txt")
    number = 1
    while output_path.exists():
        output_path = input_path.with_name(f"{input_path.stem}-{number}.txt")
        number += 1
    output_path.write_text(transcript, encoding="utf-8")
    return output_path


def normalize_words(text):
    """정렬에 사용할 문자와 숫자 단어를 추출한다."""
    return [word.casefold().replace("’", "'") for word in re.findall(r"[^\W_]+(?:['’][^\W_]+)*", text)]


def detect_lyrics_language(lyrics):
    """가사에 사용된 문자 수로 WhisperX 언어를 추정한다."""
    language_counts = {
        "ko": len(re.findall(r"[가-힣]", lyrics)),
        "ja": len(re.findall(r"[ぁ-んァ-ン]", lyrics)),
        "en": len(re.findall(r"[A-Za-z]", lyrics)),
    }
    language, count = max(language_counts.items(), key=lambda item: item[1])
    return language if count else None


def build_lyrics_prompt(lyrics):
    """빈 줄과 섹션 표기를 제외한 가사를 WhisperX 인식 힌트로 만든다."""
    prompt_lines = []
    for line in lyrics.splitlines():
        stripped = line.strip()
        if stripped and not (stripped.startswith("[") and stripped.endswith("]")):
            prompt_lines.append(stripped)
    return " ".join(prompt_lines)


def format_subtitle_timestamp(seconds, output_format):
    """초 단위 시각을 SRT 또는 VTT 타임스탬프로 변환한다."""
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, fraction = divmod(remainder, 1000)
    separator = "," if output_format == "srt" else "."
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}{separator}{fraction:03d}"


def format_lrc_timestamp(seconds):
    """초 단위 시각을 가사 텍스트의 [mm:ss.xx] 형식으로 변환한다."""
    centiseconds = max(0, round(seconds * 100))
    minutes, remainder = divmod(centiseconds, 6000)
    whole_seconds, fraction = divmod(remainder, 100)
    return f"[{minutes:02d}:{whole_seconds:02d}.{fraction:02d}]"


def convert_subtitle_timestamp(timestamp, output_format):
    """SRT/VTT 타임스탬프를 출력 형식에 맞게 변환한다."""
    if timestamp.count(":") == 1:
        timestamp = f"00:{timestamp}"
    separator = "," if output_format == "srt" else "."
    return f"{timestamp[:-4]}{separator}{timestamp[-3:]}"


def subtitle_timestamp_to_seconds(timestamp):
    """SRT/VTT 타임스탬프를 초 단위 값으로 변환한다."""
    time_part, milliseconds = timestamp.replace(",", ".").rsplit(".", 1)
    time_values = [int(value) for value in time_part.split(":")]
    if len(time_values) == 2:
        hours = 0
        minutes, seconds = time_values
    else:
        hours, minutes, seconds = time_values
    return hours * 3600 + minutes * 60 + seconds + int(milliseconds) / 1000


def parse_lrc_cues(lines, extension_seconds):
    """LRC 줄을 SRT/VTT 변환에 사용할 자막 큐로 변환한다."""
    timed_lines = []
    for line in lines:
        matches = list(LRC_TIMESTAMP_PATTERN.finditer(line))
        if not matches:
            continue
        text = line[matches[-1].end() :].strip()
        if not text:
            continue
        for match in matches:
            fraction = match["fraction"] or "0"
            start = int(match["minutes"]) * 60 + int(match["seconds"]) + int(fraction) / (10 ** len(fraction))
            timed_lines.append((start, text))

    timed_lines.sort(key=lambda item: item[0])
    cues = []
    for index, (start, text) in enumerate(timed_lines):
        end = timed_lines[index + 1][0] if index + 1 < len(timed_lines) else start + extension_seconds
        cues.append(
            (
                format_subtitle_timestamp(start, "vtt"),
                format_subtitle_timestamp(max(start, end), "vtt"),
                None,
                text,
            )
        )
    return cues


def convert_subtitle_file(input_path, output_format, position=None, extension_seconds=3.0):
    """SRT, VTT 또는 LRC 자막 파일을 지정한 형식으로 변환해 저장한다."""
    lines = input_path.read_text(encoding="utf-8-sig").splitlines()
    header_lines = []
    if input_path.suffix.lower() == ".vtt" and lines and lines[0].strip().startswith("WEBVTT"):
        header_index = 1
        while header_index < len(lines) and lines[header_index].strip():
            header_lines.append(lines[header_index])
            header_index += 1

    if input_path.suffix.lower() == ".lrc":
        cues = parse_lrc_cues(lines, extension_seconds)
    else:
        cues = []
        line_index = 0
        while line_index < len(lines):
            match = SUBTITLE_TIMESTAMP_PATTERN.fullmatch(lines[line_index].strip())
            if match is None:
                line_index += 1
                continue
            line_index += 1
            text_lines = []
            while line_index < len(lines) and lines[line_index].strip():
                text_lines.append(lines[line_index])
                line_index += 1
            cues.append((match["start"], match["end"], match["settings"], "\n".join(text_lines)))

    if not cues:
        raise SttError(f"자막 큐를 찾을 수 없습니다: {input_path}")

    converted_cues = []
    for cue_number, (start, end, settings, text) in enumerate(cues, start=1):
        if output_format == "lrc":
            converted_cues.append(
                f"{format_lrc_timestamp(subtitle_timestamp_to_seconds(start))}{' '.join(text.splitlines())}"
            )
            continue
        timestamp = (
            f"{convert_subtitle_timestamp(start, output_format)} --> "
            f"{convert_subtitle_timestamp(end, output_format)}"
        )
        if output_format == "vtt":
            cue_settings = position or settings
            if cue_settings:
                timestamp = f"{timestamp} {cue_settings}"
            converted_cues.append(f"{timestamp}\n{text}")
        else:
            converted_cues.append(f"{cue_number}\n{timestamp}\n{text}")

    prefix = ""
    if output_format == "vtt":
        prefix = "WEBVTT\n"
        if header_lines:
            prefix += "\n".join(header_lines) + "\n"
        prefix += "\n"
    separator = "\n" if output_format == "lrc" else "\n\n"
    converted_subtitles = prefix + separator.join(converted_cues) + "\n"
    output_path = input_path.with_suffix(f".{output_format}")
    number = 1
    while output_path.exists():
        output_path = input_path.with_name(f"{input_path.stem}-{number}.{output_format}")
        number += 1
    output_path.write_text(converted_subtitles, encoding="utf-8")
    return output_path, converted_subtitles


def separate_vocals(input_path):
    """Audio Separator로 보컬 FLAC을 분리하거나 기존 보컬 파일을 재사용한다."""
    input_path = input_path.resolve()
    vocal_path = input_path.with_name(f"{input_path.stem}-vocal.flac")
    if vocal_path.is_file():
        print(f"기존 보컬 파일 사용: {vocal_path}", flush=True)
        return vocal_path

    if not AUDIO_SEPARATOR_EXECUTABLE.is_file():
        raise SttError(f"Audio Separator 실행 파일을 찾을 수 없습니다: {AUDIO_SEPARATOR_EXECUTABLE}")

    with tempfile.TemporaryDirectory(prefix="stt_vocals_", dir=input_path.parent) as output_dir:
        output_path = Path(output_dir)
        command = [
            str(AUDIO_SEPARATOR_EXECUTABLE),
            str(input_path),
            "--model_filename",
            AUDIO_SEPARATOR_MODEL,
            "--single_stem",
            "Vocals",
            "--output_format",
            "FLAC",
            "--output_dir",
            str(output_path),
            "--model_file_dir",
            str(AUDIO_SEPARATOR_MODEL_DIR),
        ]
        print(f"Audio Separator 실행 명령: {subprocess.list2cmdline(command)}", flush=True)
        result = subprocess.run(command, check=False)
        if result.returncode != 0:
            raise SttError(f"Audio Separator 실행에 실패했습니다. 종료 코드: {result.returncode}")

        vocal_paths = list(output_path.glob("*.flac"))
        if len(vocal_paths) != 1:
            raise SttError("Audio Separator 보컬 결과 FLAC 파일을 찾을 수 없습니다.")
        vocal_paths[0].replace(vocal_path)
    return vocal_path


def get_whisper_result(input_path, language=None, prompt=None):
    """WhisperX JSON을 생성하거나 기존 JSON을 읽어 반환한다."""
    input_path = input_path.resolve()
    lyrics_result_path = input_path.with_name(f"{input_path.stem}-vocal.json")
    if prompt:
        audio_path = separate_vocals(input_path)
        result_path = lyrics_result_path
    elif lyrics_result_path.is_file():
        audio_path = input_path
        result_path = lyrics_result_path
    else:
        audio_path = input_path
        result_path = input_path.with_name(f"{input_path.stem}-auto.json")
    if result_path.is_file():
        print(f"기존 WhisperX JSON 파일 사용: {result_path}", flush=True)
    else:
        if not WHISPERX_EXECUTABLE.is_file():
            raise SttError(f"WhisperX 실행 파일을 찾을 수 없습니다: {WHISPERX_EXECUTABLE}")
        with tempfile.TemporaryDirectory(prefix="stt_whisperx_") as temp_dir:
            temp_path = Path(temp_dir)
            command = [
                str(WHISPERX_EXECUTABLE),
                str(audio_path),
                "--model",
                "large-v3",
                "--device",
                "cuda",
                "--compute_type",
                "float16",
                "--output_format",
                "json",
                "--output_dir",
                str(temp_path),
            ]
            if language:
                command.extend(("--language", language.split("-")[0].lower()))
            if prompt:
                command.extend(("--initial_prompt", prompt, "--hotwords", prompt))
            print(f"WhisperX 실행 명령: {subprocess.list2cmdline(command)}", flush=True)
            result = subprocess.run(command, check=False)
            if result.returncode != 0:
                raise SttError(f"WhisperX 실행에 실패했습니다. 종료 코드: {result.returncode}")
            temp_result_path = temp_path / f"{audio_path.stem}.json"
            if not temp_result_path.is_file():
                raise SttError("WhisperX 결과 JSON 파일이 생성되지 않았습니다.")
            shutil.copy2(temp_result_path, result_path)
            print(f"WhisperX JSON 저장 파일: {result_path}", flush=True)

    try:
        return json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SttError(f"WhisperX JSON 파일을 읽을 수 없습니다: {result_path}") from error


def add_lyrics_timestamps(
    lyrics, whisper_result, output_format, position_setting=None, extension_seconds=3.0
):
    """WhisperX 단어 시각을 원문 가사 줄에 대응시켜 시간 가사 또는 자막으로 만든다."""
    lines = lyrics.splitlines()
    lyric_words = []
    word_line_indexes = []
    vocal_line_indexes = []
    line_texts = {}
    for line_index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or (stripped.startswith("[") and stripped.endswith("]")):
            continue
        words = normalize_words(line)
        if words:
            vocal_line_indexes.append(line_index)
            line_texts[line_index] = stripped
            lyric_words.extend(words)
            word_line_indexes.extend([line_index] * len(words))

    transcript_words = []
    transcript_starts = []
    transcript_ends = []
    transcript_end = 0.0
    for word_data in whisper_result.get("word_segments", []):
        words = normalize_words(str(word_data.get("word", "")))
        start = word_data.get("start")
        if start is None:
            continue
        start = float(start)
        end = float(word_data.get("end", start))
        transcript_words.extend(words)
        transcript_starts.extend([start] * len(words))
        transcript_ends.extend([end] * len(words))
        transcript_end = max(transcript_end, end)

    if not transcript_words:
        raise SttError("WhisperX 결과에서 단어 시간 정보를 찾을 수 없습니다.")

    line_starts = {}
    line_ends = {}
    matcher = difflib.SequenceMatcher(None, lyric_words, transcript_words, autojunk=False)
    matched_word_count = 0
    for block in matcher.get_matching_blocks():
        matched_word_count += block.size
        for offset in range(block.size):
            line_index = word_line_indexes[block.a + offset]
            transcript_index = block.b + offset
            line_starts.setdefault(line_index, transcript_starts[transcript_index])
            line_ends[line_index] = max(line_ends.get(line_index, 0.0), transcript_ends[transcript_index])

    minimum_matches = max(2, min(len(lyric_words), len(transcript_words)) // 20)
    if matched_word_count < minimum_matches:
        raise SttError("가사와 WhisperX 인식 결과의 일치율이 너무 낮습니다. --lang 옵션을 확인하세요.")

    matched_positions = [
        position for position, line_index in enumerate(vocal_line_indexes) if line_index in line_starts
    ]
    if not matched_positions:
        raise SttError("가사와 WhisperX 인식 결과에서 일치하는 단어를 찾을 수 없습니다.")

    for position, line_index in enumerate(vocal_line_indexes):
        if line_index in line_starts:
            continue
        previous_positions = [matched for matched in matched_positions if matched < position]
        next_positions = [matched for matched in matched_positions if matched > position]
        if previous_positions and next_positions:
            previous_position = previous_positions[-1]
            next_position = next_positions[0]
            previous_start = line_starts[vocal_line_indexes[previous_position]]
            next_start = line_starts[vocal_line_indexes[next_position]]
            ratio = (position - previous_position) / (next_position - previous_position)
            line_starts[line_index] = previous_start + (next_start - previous_start) * ratio
        elif next_positions:
            next_position = next_positions[0]
            next_start = line_starts[vocal_line_indexes[next_position]]
            line_starts[line_index] = next_start * position / next_position
        else:
            previous_position = previous_positions[-1]
            previous_start = line_starts[vocal_line_indexes[previous_position]]
            remaining_lines = len(vocal_line_indexes) - previous_position
            final_end = max(transcript_end, previous_start + 1.0)
            line_starts[line_index] = (
                previous_start
                + (final_end - previous_start) * (position - previous_position) / remaining_lines
            )

    if output_format in (None, "lrc"):
        return (
            "\n".join(
                f"{format_lrc_timestamp(line_starts[line_index])}{line_texts[line_index]}"
                for line_index in vocal_line_indexes
            )
            + "\n"
        )

    cues = []
    for position, line_index in enumerate(vocal_line_indexes):
        start = line_starts[line_index]
        if line_index in line_ends:
            end = line_ends[line_index] + extension_seconds
        elif position + 1 < len(vocal_line_indexes):
            end = line_starts[vocal_line_indexes[position + 1]]
        else:
            end = max(transcript_end, start + 0.5)
        if position + 1 < len(vocal_line_indexes):
            end = min(end, line_starts[vocal_line_indexes[position + 1]])
        timestamp = (
            f"{format_subtitle_timestamp(start, output_format)} --> "
            f"{format_subtitle_timestamp(end, output_format)}"
        )
        if output_format == "vtt" and position_setting:
            timestamp = f"{timestamp} {position_setting}"
        if output_format == "srt":
            cues.append(f"{position + 1}\n{timestamp}\n{line_texts[line_index]}")
        else:
            cues.append(f"{timestamp}\n{line_texts[line_index]}")

    prefix = "WEBVTT\n\n" if output_format == "vtt" else ""
    return prefix + "\n\n".join(cues) + "\n"


def format_whisper_subtitles(whisper_result, output_format, position_setting=None, extension_seconds=3.0):
    """WhisperX 단어 시각을 휴지 구간과 문장부호로 나눠 SRT, VTT 또는 LRC로 만든다."""
    words = []
    for word_data in whisper_result.get("word_segments", []):
        text = str(word_data.get("word", "")).strip()
        start = word_data.get("start")
        if not text or start is None:
            continue
        start = float(start)
        words.append((start, float(word_data.get("end", start)), text))

    segments = []
    if words:
        cue_start = words[0][0]
        cue_words = []
        for index, (start, end, text) in enumerate(words):
            cue_words.append(text)
            next_start = words[index + 1][0] if index + 1 < len(words) else None
            sentence_end = re.search(r"[.!?。！？][\"'’”)]*$", text) is not None
            long_pause = next_start is not None and next_start - end >= 0.7
            if next_start is None or sentence_end or long_pause:
                segments.append((cue_start, end + extension_seconds, " ".join(cue_words)))
                cue_words = []
                if next_start is not None:
                    cue_start = next_start
    else:
        for segment_data in whisper_result.get("segments", []):
            text = str(segment_data.get("text", "")).strip()
            start = segment_data.get("start")
            if not text or start is None:
                continue
            start = float(start)
            end = float(segment_data.get("end", start)) + extension_seconds
            segments.append((start, end, text))

    if not segments:
        raise SttError("WhisperX 결과에서 자막 세그먼트를 찾을 수 없습니다.")

    if output_format == "lrc":
        return (
            "\n".join(
                f"{format_lrc_timestamp(start)}{' '.join(text.splitlines())}"
                for start, _end, text in segments
            )
            + "\n"
        )

    cues = []
    for index, (start, end, text) in enumerate(segments):
        if index + 1 < len(segments):
            end = min(end, segments[index + 1][0])
        timestamp = (
            f"{format_subtitle_timestamp(start, output_format)} --> "
            f"{format_subtitle_timestamp(end, output_format)}"
        )
        if output_format == "vtt" and position_setting:
            timestamp = f"{timestamp} {position_setting}"
        if output_format == "srt":
            cues.append(f"{index + 1}\n{timestamp}\n{text}")
        else:
            cues.append(f"{timestamp}\n{text}")

    prefix = "WEBVTT\n\n" if output_format == "vtt" else ""
    return prefix + "\n\n".join(cues) + "\n"


def create_auto_subtitles(input_path, output_format, language=None, position=None, extension_seconds=3.0):
    """WhisperX 자동 인식 결과로 SRT, VTT 또는 LRC 자막 파일을 저장한다."""
    whisper_result = get_whisper_result(input_path, language)
    subtitles = format_whisper_subtitles(whisper_result, output_format, position, extension_seconds)
    output_path = input_path.with_suffix(f".{output_format}")
    number = 1
    while output_path.exists():
        output_path = input_path.with_name(f"{input_path.stem}-{number}.{output_format}")
        number += 1
    output_path.write_text(subtitles, encoding="utf-8")
    return output_path, subtitles


def create_timed_lyrics(
    input_path, lyrics_path, output_format, language=None, position=None, extension_seconds=3.0
):
    """WhisperX JSON을 생성하거나 재사용해 시간 정보가 추가된 가사 파일을 저장한다."""
    if not lyrics_path.is_file():
        raise SttError(f"가사 파일을 찾을 수 없습니다: {lyrics_path}")

    lyrics = lyrics_path.read_text(encoding="utf-8-sig")
    language = language or detect_lyrics_language(lyrics)
    lyrics_prompt = build_lyrics_prompt(lyrics)
    whisper_result = get_whisper_result(input_path, language, lyrics_prompt)

    timed_lyrics = add_lyrics_timestamps(lyrics, whisper_result, output_format, position, extension_seconds)
    if output_format is None:
        output_path = lyrics_path.with_name(f"{lyrics_path.stem}-time.txt")
    else:
        output_path = lyrics_path.with_name(f"{lyrics_path.stem}.{output_format}")
        number = 1
        while output_path.exists():
            output_path = lyrics_path.with_name(f"{lyrics_path.stem}-{number}.{output_format}")
            number += 1
    output_path.write_text(timed_lyrics, encoding="utf-8")
    return output_path, timed_lyrics


def format_execution_time(end_time, elapsed_seconds):
    """작업 종료 시각과 경과 시간을 표시할 문자열로 만든다."""
    elapsed_milliseconds = round(elapsed_seconds * 1000)
    hours, remainder = divmod(elapsed_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
    return (
        "\n--- 작업 시간 ---\n"
        f"종료 시간: {end_time:%Y-%m-%d %H:%M:%S}\n"
        f"걸린 시간: {hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
    )


def transcribe_google(audio_paths, language):
    """Google Cloud Speech-to-Text V2 Chirp 3로 오디오 조각을 전사한다."""
    try:
        from google.api_core.exceptions import GoogleAPICallError, PermissionDenied
        from google.auth.exceptions import DefaultCredentialsError
        from google.cloud import speech_v2
    except ImportError as error:
        raise SttError("google-cloud-speech 패키지가 필요합니다: pip install google-cloud-speech") from error

    try:
        dotenv = importlib.import_module("dotenv")
    except ModuleNotFoundError as error:
        raise SttError("python-dotenv 패키지가 필요합니다: pip install python-dotenv") from error

    env_path = Path(__file__).resolve().parents[2] / ".env"
    env_values = dotenv.dotenv_values(env_path)
    project_id = env_values.get("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        raise SttError(f"{env_path} 파일에 GOOGLE_CLOUD_PROJECT를 설정하세요.")

    language_codes = {"ko": "ko-KR", "en": "en-US", "ja": "ja-JP"}
    language_code = language_codes.get(language.lower(), language)

    try:
        client = speech_v2.SpeechClient(
            client_options={"api_endpoint": f"{GOOGLE_REGION}-speech.googleapis.com"}
        )
    except DefaultCredentialsError as error:
        raise SttError(
            "Google ADC 인증이 필요합니다. 다음 명령을 실행하세요: " "gcloud auth application-default login"
        ) from error
    config = speech_v2.RecognitionConfig(
        auto_decoding_config=speech_v2.AutoDetectDecodingConfig(),
        language_codes=[language_code],
        model="chirp_3",
        features=speech_v2.RecognitionFeatures(enable_automatic_punctuation=True),
    )
    transcripts = []
    for audio_path in audio_paths:
        request = speech_v2.RecognizeRequest(
            recognizer=f"projects/{project_id}/locations/{GOOGLE_REGION}/recognizers/_",
            config=config,
            content=audio_path.read_bytes(),
        )
        try:
            response = client.recognize(request=request)
        except PermissionDenied as error:
            raise SttError(
                f"Google 계정에 프로젝트 {project_id}의 Cloud Speech Client "
                "역할(roles/speech.client)이 필요합니다."
            ) from error
        except GoogleAPICallError as error:
            raise SttError(f"Google Speech-to-Text API 오류: {error}") from error
        transcripts.extend(
            result.alternatives[0].transcript.strip() for result in response.results if result.alternatives
        )
    return "\n".join(filter(None, transcripts))


def transcribe_openai(audio_paths, language):
    """OpenAI Speech API로 오디오 조각을 전사한다."""
    try:
        openai = importlib.import_module("openai")
    except ModuleNotFoundError as error:
        raise SttError("openai 패키지가 필요합니다: pip install openai") from error

    try:
        dotenv = importlib.import_module("dotenv")
    except ModuleNotFoundError as error:
        raise SttError("python-dotenv 패키지가 필요합니다: pip install python-dotenv") from error

    env_path = Path(__file__).resolve().parents[2] / ".env"
    api_key = dotenv.dotenv_values(env_path).get("OPENAI_API_KEY")
    if not api_key:
        raise SttError(f"{env_path} 파일에 OPENAI_API_KEY를 설정하세요.")

    client = openai.OpenAI(api_key=api_key)
    transcripts = []
    for audio_path in audio_paths:
        with audio_path.open("rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="gpt-4o-transcribe", file=audio_file, language=language.split("-")[0].lower()
            )
        text = transcript.text.strip()
        if text:
            transcripts.append(text)
    return "\n".join(transcripts)


def parse_args(argv=None):
    """명령행 인수를 읽는다."""
    parser = argparse.ArgumentParser(
        description="오디오·동영상 파일을 텍스트로 변환하거나 자막 파일 형식을 변환합니다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''명령 예제:
  python stt.py input.mp3 --api google --lang ko
  python stt.py input.mp3 --api openai --lang en
  python stt.py sky.srt --format vtt --position 4
  python stt.py song.vtt --format lrc
  python stt.py song.lrc --format srt
  python stt.py input.mp3 --format lrc
  python stt.py input.mp3 --format vtt --position "line:-4 position:50% align:center" --extend 5
  python stt.py input.flac --lyrics input.txt
  python stt.py input.flac --lyrics call-lyrics.txt --format srt
  python stt.py input.flac --lyrics call-lyrics.txt --format vtt --lang en
  python stt.py input.flac --lyrics input.txt --format vtt --position "line:-4 position:50% align:center"''',
    )
    parser.add_argument("input_file", metavar="입력파일", type=Path, help="오디오, 동영상 또는 자막 파일")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--api", choices=("google", "openai"), help="사용할 음성 인식 API")
    mode.add_argument("--lyrics", type=Path, help="시간 정보를 추가할 가사 파일")
    parser.add_argument(
        "--lang", help="오디오 언어 코드 (가사 모드는 생략 시 자동 감지, API 모드는 기본값 ko)"
    )
    parser.add_argument(
        "--format", choices=("srt", "vtt", "lrc"), help="자막 출력 형식 (--lyrics 생략 시 자동 인식)"
    )
    parser.add_argument(
        "--position", help="VTT 자막 위치 설정 (예: 4 또는 line:-4 position:50%% align:center)"
    )
    parser.add_argument("--extend", type=float, default=3.0, help="자막 표시 연장 시간(초, 기본값: 3)")
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        parser.print_help()
        return None
    args = parser.parse_args(argv)
    if not (args.api or args.lyrics or args.format):
        parser.error("--api, --lyrics 또는 --format 중 하나가 필요합니다.")
    if args.api and args.format:
        parser.error("--api와 --format은 함께 사용할 수 없습니다.")
    if args.format == "vtt" and args.position and re.fullmatch(r"[0-9]+", args.position):
        args.position = f"line:-{args.position} position:50% align:center"
    if not math.isfinite(args.extend) or args.extend < 0:
        parser.error("--extend는 0 이상의 유한한 숫자여야 합니다.")
    return args


def main(argv=None):
    """STT 명령행 프로그램을 실행한다."""
    args = parse_args(argv)
    if args is None:
        return

    start_time = datetime.now()
    start_counter = time.perf_counter()
    is_subtitle_input = args.input_file.suffix.lower() in (".srt", ".vtt", ".lrc")
    if is_subtitle_input:
        print(f"작업 시작: {args.input_file} 자막을 {args.format or '미지정'} 형식으로 변환", flush=True)
    elif args.lyrics:
        print(f"작업 시작: {args.input_file} 음성을 분석하여 {args.lyrics} 가사에 시간 정보 추가", flush=True)
    elif args.format:
        print(f"작업 시작: WhisperX로 {args.input_file} 자동 자막 생성", flush=True)
    else:
        print(f"작업 시작: {args.api} API로 {args.input_file} 음성을 텍스트로 변환", flush=True)
    print(f"작업 시작 시간: {start_time:%Y-%m-%d %H:%M:%S}", flush=True)
    if not args.input_file.is_file():
        raise SttError(f"입력 파일을 찾을 수 없습니다: {args.input_file}")

    if is_subtitle_input:
        if args.format is None:
            raise SttError("자막 파일을 변환하려면 --format srt, vtt 또는 lrc가 필요합니다.")
        output_path, result = convert_subtitle_file(args.input_file, args.format, args.position, args.extend)
        end_time = datetime.now()
        elapsed_seconds = time.perf_counter() - start_counter
        print(result)
        print(f"저장 파일: {output_path}")
        print(format_execution_time(end_time, elapsed_seconds))
        return

    if args.lyrics:
        output_path, result = create_timed_lyrics(
            args.input_file, args.lyrics, args.format, args.lang, args.position, args.extend
        )
        end_time = datetime.now()
        elapsed_seconds = time.perf_counter() - start_counter
        print(result)
        print(f"저장 파일: {output_path}")
        print(format_execution_time(end_time, elapsed_seconds))
        return

    if args.format:
        output_path, result = create_auto_subtitles(
            args.input_file, args.format, args.lang, args.position, args.extend
        )
        end_time = datetime.now()
        elapsed_seconds = time.perf_counter() - start_counter
        print(result)
        print(f"저장 파일: {output_path}")
        print(format_execution_time(end_time, elapsed_seconds))
        return

    with tempfile.TemporaryDirectory(prefix="stt_") as temp_dir:
        audio_paths = convert_to_audio_chunks(args.input_file, Path(temp_dir))
        durations = get_audio_durations(audio_paths)
        if args.api == "google":
            result = transcribe_google(audio_paths, args.lang or "ko")
        else:
            result = transcribe_openai(audio_paths, args.lang or "ko")

    output_path = save_transcript(args.input_file, result)
    end_time = datetime.now()
    elapsed_seconds = time.perf_counter() - start_counter
    print(result)
    print(format_usage(args.api, durations))
    print(f"저장 파일: {output_path}")
    print(format_execution_time(end_time, elapsed_seconds))


if __name__ == "__main__":
    try:
        main()
    except SttError as error:
        print(f"오류: {error}", file=sys.stderr)
        raise SystemExit(1)
