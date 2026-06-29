"""
유틸리티 함수 모듈
C++ apFile, apLib 등의 유틸리티 함수 포팅
"""

import os
import re
from typing import Tuple, Optional

# 코덱 상수 (출력 파일 확장자 결정용)
CODEC_264 = 1
CODEC_265 = 2
CODEC_AV1 = 3
CODEC_GIF = 4
CODEC_WEBP = 5
CODEC_WAV = 6
CODEC_FLAC = 7
CODEC_MP3 = 8
CODEC_OGG = 9
CODEC_OPUS = 10
CODEC_AAC = 11
CODEC_AVIF = 33


# 비디오 확장자
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".webm", ".mpg", ".mov", ".wmv", ".ts", ".flv", ".m4v"}

# 오디오 확장자
AUDIO_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".aac",
    ".opus",
    ".ogg",
    ".ac3",
    ".mka",
    ".ape",
    ".flc",
    ".flac",
    ".wma",
    ".dts",
    ".m4a",
}

# 태그 삭제 대상 오디오 확장자
TAG_DELETE_AUDIO_EXTENSIONS = {".mp3", ".flac", ".wav", ".opus", ".aac", ".ogg"}

# 이미지 확장자
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".avif"}


def get_extension(filepath: str) -> str:
    """파일 확장자 추출 (소문자)"""
    _, ext = os.path.splitext(filepath)
    return ext.lower()


def is_video_file(filepath: str) -> bool:
    """비디오 파일 여부 확인"""
    ext = get_extension(filepath)
    return ext in VIDEO_EXTENSIONS


def is_audio_file(filepath: str) -> bool:
    """오디오 파일 여부 확인"""
    ext = get_extension(filepath)
    return ext in AUDIO_EXTENSIONS


def is_tag_delete_audio_file(filepath: str) -> bool:
    """태그 삭제 대상 오디오 파일 여부 확인"""
    ext = get_extension(filepath)
    return ext in TAG_DELETE_AUDIO_EXTENSIONS


def is_image_file(filepath: str) -> bool:
    """이미지 파일 여부 확인"""
    ext = get_extension(filepath)
    return ext in IMAGE_EXTENSIONS


def divide_name(filepath: str) -> Tuple[str, str]:
    """파일 경로를 이름과 확장자로 분리

    Returns:
        (이름 부분, 확장자) - 확장자는 '.' 제외
    """
    name, ext = os.path.splitext(filepath)
    return name, ext[1:] if ext else ""


def get_output_filename(input_file: str, output_codec: int, settings: dict = None, media_info=None) -> str:
    """출력 파일명 생성 (중복 방지)

    Args:
        input_file: 입력 파일 경로
        output_codec: 출력 코덱
        settings: 설정 딕셔너리
        media_info: 미디어 정보 (오디오 추출 시 확장자 결정용)

    Returns:
        출력 파일 경로
    """
    if settings is None:
        settings = {}

    name, ext = divide_name(input_file)
    ext = ext.lower()

    process_kind = settings.get("process_kind", 3)  # PROC_KIND_CONVERT

    # 합치기의 경우 .ts 확장자
    if process_kind == 4:  # PROC_KIND_MERGE
        return f"{name}.ts"

    # 출력 확장자 결정
    new_ext = ext

    audio_output_codecs = {CODEC_WAV, CODEC_FLAC, CODEC_MP3, CODEC_OGG, CODEC_OPUS, CODEC_AAC}

    if process_kind != 7 or output_codec in audio_output_codecs:  # PROC_KIND_DELETE_TAGS
        # 포맷 강제 지정
        if settings.get("mp4", False):
            new_ext = "mp4"
        elif settings.get("mkv", False):
            new_ext = "mkv"

        # 코덱별 확장자
        codec_extensions = {
            CODEC_AV1: "mp4",
            CODEC_AVIF: "avif",
            CODEC_GIF: "gif",
            CODEC_WEBP: "webp",
            CODEC_WAV: "wav",
            CODEC_FLAC: "flac",
            CODEC_MP3: "mp3",
            CODEC_OGG: "ogg",
            CODEC_OPUS: "opus",
            CODEC_AAC: "aac",
        }

        if output_codec in codec_extensions:
            new_ext = codec_extensions[output_codec]
        elif process_kind != 7 and output_codec in [CODEC_264, CODEC_265]:
            # 비디오 코덱인데 비디오 확장자가 아닌 경우
            if new_ext not in ["mp4", "mkv"]:
                new_ext = "mp4"

        # 오디오 추출인 경우: 오디오 스트림의 코덱에 맞는 확장자 사용
        if process_kind == 2 and media_info is not None:  # PROC_KIND_EXTRACT_AUDIO
            audio_codec_ext = {
                51: "mp3",   # A_CODEC_MP3
                52: "aac",   # A_CODEC_AAC
                53: "ogg",   # A_CODEC_OGG
                54: "dts",   # A_CODEC_DTS
                55: "wav",   # A_CODEC_WAV
                56: "ac3",   # A_CODEC_AC3
                57: "opus",  # A_CODEC_OPUS
                58: "flac",  # A_CODEC_FLAC
                59: "mka",   # A_CODEC_MKA
            }
            audio_sel = settings.get("audio_sel", []) if settings else []
            track_idx = audio_sel[0] if audio_sel else 0
            if hasattr(media_info, 'audio_tracks') and track_idx < len(media_info.audio_tracks):
                a_codec = media_info.audio_tracks[track_idx].codec
                if a_codec in audio_codec_ext:
                    new_ext = audio_codec_ext[a_codec]

    # 이미 생성된 이름인지 확인 (_(02) 형태)
    match = re.search(r"_\((\d+)\)$", name)
    start_num = 2
    if match:
        start_num = int(match.group(1))
        name = name[: match.start()]

    if process_kind == 8 and not name.endswith("-n"):  # PROC_KIND_NORMALIZATION
        name = f"{name}-n"

    # 중복 파일 확인
    output_file = f"{name}.{new_ext}"

    for i in range(start_num, 100):
        if not os.path.exists(output_file):
            break
        output_file = f"{name}_({i:02d}).{new_ext}"

    return output_file


def time_to_seconds(h: int, m: int, s: int) -> int:
    """시:분:초를 초로 변환"""
    return h * 3600 + m * 60 + s


def seconds_to_time(seconds: int) -> Tuple[int, int, int]:
    """초를 시:분:초로 변환"""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return h, m, s


def calc_video_resolution(w: int, h: int, target_w: int = 0, target_h: int = 0) -> int:
    """비디오 해상도 계산 (비율 유지, 짝수로)

    Args:
        w, h: 원본 가로, 세로
        target_w: 목표 가로 (0이면 세로로 계산)
        target_h: 목표 세로 (0이면 가로로 계산)

    Returns:
        계산된 가로 또는 세로
    """
    if target_h == 0 and target_w > 0:
        # 가로 고정, 세로 계산
        new_h = round((h * target_w) / w)
        new_h += new_h % 2  # 짝수로
        return new_h
    elif target_w == 0 and target_h > 0:
        # 세로 고정, 가로 계산
        new_w = round((w * target_h) / h)
        new_w += new_w % 2  # 짝수로
        return new_w
    return 0


def format_size(size_bytes: int) -> str:
    """바이트를 사람이 읽기 쉬운 형태로 변환"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.2f} MB"
    else:
        return f"{size_bytes / 1024 / 1024 / 1024:.2f} GB"


def format_duration(seconds: int) -> str:
    """초를 시:분:초 형태로 변환"""
    h, m, s = seconds_to_time(seconds)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    else:
        return f"{m}:{s:02d}"


def get_app_path() -> str:
    """애플리케이션 경로 반환"""
    return os.path.dirname(os.path.abspath(__file__))


def ensure_dir(path: str):
    """디렉토리 존재 확인 및 생성"""
    if not os.path.exists(path):
        os.makedirs(path)


def file_exists(path: str) -> bool:
    """파일 존재 여부 확인"""
    return os.path.isfile(path)


def get_file_size(path: str) -> int:
    """파일 크기 반환"""
    if os.path.exists(path):
        return os.path.getsize(path)
    return 0


def sanitize_filename(filename: str) -> str:
    """파일명에서 사용할 수 없는 문자 제거"""
    # Windows에서 사용할 수 없는 문자들
    invalid_chars = r'<>:"/\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, "_")
    return filename


class FileHelper:
    """파일 처리 헬퍼 클래스 (C++ apFile 대응)"""

    @staticmethod
    def read_file(filepath: str) -> Optional[str]:
        """텍스트 파일 읽기"""
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception as e:
            print(f"파일 읽기 오류: {e}")
            return None

    @staticmethod
    def read_lines(filepath: str) -> list:
        """텍스트 파일을 줄 단위로 읽기"""
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                return f.readlines()
        except Exception as e:
            print(f"파일 읽기 오류: {e}")
            return []

    @staticmethod
    def write_file(filepath: str, content: str, append: bool = False) -> bool:
        """텍스트 파일 쓰기"""
        try:
            mode = "a" if append else "w"
            with open(filepath, mode, encoding="utf-8") as f:
                f.write(content)
            return True
        except Exception as e:
            print(f"파일 쓰기 오류: {e}")
            return False

    @staticmethod
    def write_binary(filepath: str, data: bytes, offset: int = 0) -> bool:
        """바이너리 파일 쓰기"""
        try:
            mode = "r+b" if os.path.exists(filepath) else "wb"
            with open(filepath, mode) as f:
                if offset > 0:
                    f.seek(offset)
                f.write(data)
            return True
        except Exception as e:
            print(f"바이너리 쓰기 오류: {e}")
            return False


if __name__ == "__main__":
    # 테스트
    print(f"is_video_file('test.mp4'): {is_video_file('test.mp4')}")
    print(f"is_audio_file('test.mp3'): {is_audio_file('test.mp3')}")
    print(f"divide_name('C:/path/file.mp4'): {divide_name('C:/path/file.mp4')}")
    print(f"format_size(1024*1024*50): {format_size(1024*1024*50)}")
    print(f"format_duration(3661): {format_duration(3661)}")
