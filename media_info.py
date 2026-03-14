"""
MediaInfo 파싱 모듈
C++ MediaInfoGet, MediaInfoFileRead, MediaLineAnalyze 함수 포팅
"""

import os
import subprocess
import re
import json
from dataclasses import dataclass, field
from typing import List, Optional
import math

# 코덱 상수
CODEC_UNKNOWN = 0
CODEC_264 = 1  # AVC
CODEC_AVC = 1
CODEC_265 = 2  # HEVC
CODEC_HEVC = 2
CODEC_AV1 = 3
CODEC_GIF = 4
CODEC_WEBP = 5
CODEC_VP9 = 36
CODEC_VP8 = 37
CODEC_VP7 = 38
CODEC_XVID = 34
CODEC_DX50 = 35

# 오디오 코덱 상수
A_CODEC_UNKNOWN = 0
A_CODEC_MP3 = 51
A_CODEC_AAC = 52
A_CODEC_OGG = 53
A_CODEC_DTS = 54
A_CODEC_WAV = 55
A_CODEC_AC3 = 56
A_CODEC_OPUS = 57
A_CODEC_FLAC = 58
A_CODEC_MKA = 59

# 언어 상수
LANG_KOREAN = 0x12
LANG_ENGLISH = 0x09
LANG_JAPANESE = 0x11
LANG_CHINESE = 0x04
LANG_SPANISH = 0x0A
LANG_FRENCH = 0x0C
LANG_ITALIAN = 0x10
LANG_GERMAN = 0x07
LANG_GREEK = 0x08
LANG_HINDI = 0x39


@dataclass
class SubInfo:
    """자막 트랙 정보"""

    codec: str = ""  # subrip, ass, mov_text, dvb_subtitle, hdmv_pgs_subtitle 등
    lang: int = 0
    title: str = ""
    sdh: bool = False
    forced: bool = False

    @property
    def extension(self) -> str:
        """자막 코덱에 맞는 확장자 반환"""
        ext_map = {
            "subrip": "srt",
            "srt": "srt",
            "ass": "ass",
            "ssa": "ssa",
            "mov_text": "srt",
            "webvtt": "vtt",
            "hdmv_pgs_subtitle": "sup",
            "dvd_subtitle": "sup",
            "dvb_subtitle": "sup",
        }
        return ext_map.get(self.codec, "srt")

    @property
    def lang_name(self) -> str:
        """언어 이름 반환"""
        lang_names = {
            LANG_KOREAN: "KO",
            LANG_ENGLISH: "EN",
            LANG_JAPANESE: "JA",
            LANG_CHINESE: "ZH",
            LANG_SPANISH: "ES",
            LANG_FRENCH: "FR",
            LANG_ITALIAN: "IT",
            LANG_GERMAN: "DE",
        }
        return lang_names.get(self.lang, "")

    @property
    def suffix(self) -> str:
        """파일명에 붙일 자막 정보 접미사 (예: .ko.sdh, .en.forced)"""
        parts = []
        if self.lang_name:
            parts.append(self.lang_name.lower())
        if self.sdh:
            parts.append("sdh")
        if self.forced:
            parts.append("forced")
        if self.title and not self.sdh and not self.forced:
            t = self.title.strip()
            t_upper = t.upper()
            # title에 lang/SDH/forced 외 유용한 정보가 있으면 추가
            if "SDH" not in t_upper and "FORCED" not in t_upper and t_upper not in ("", self.lang_name):
                parts.append(t)
        return ".".join(parts)


@dataclass
class AudioInfo:
    """오디오 트랙 정보"""

    size: int = 0
    duration: int = 0
    codec: int = 0
    bitrate: int = 0
    channel: int = 0
    lang: int = 0

    @property
    def codec_name(self) -> str:
        """코덱 이름 반환"""
        codec_names = {
            A_CODEC_MP3: "MP3",
            A_CODEC_AAC: "AAC",
            A_CODEC_OGG: "OGG",
            A_CODEC_AC3: "AC3",
            A_CODEC_MKA: "MKA",
            A_CODEC_DTS: "DTS",
            A_CODEC_WAV: "WAV",
            A_CODEC_OPUS: "OPUS",
            A_CODEC_FLAC: "FLAC",
        }
        return codec_names.get(self.codec, "")

    @property
    def lang_name(self) -> str:
        """언어 이름 반환"""
        lang_names = {
            LANG_KOREAN: "KO",
            LANG_ENGLISH: "EN",
            LANG_JAPANESE: "JA",
            LANG_CHINESE: "ZH",
            LANG_SPANISH: "ES",
            LANG_FRENCH: "FR",
            LANG_ITALIAN: "IT",
            LANG_GERMAN: "DE",
        }
        return lang_names.get(self.lang, "")


@dataclass
class MEDIA_INFO:
    """미디어 파일 정보 구조체"""

    filename: str = ""
    file_size: int = 0
    file_duration: int = 0

    # 비디오 정보
    size: int = 0
    duration: int = 0
    codec: int = 0
    bitrate: int = 0
    width: int = 0
    height: int = 0
    frame_rate: float = 0.0
    vfr: bool = False
    depth: int = 0

    # 오디오 정보
    audio_tracks: List[AudioInfo] = field(default_factory=list)
    audio_count: int = 0

    # 자막 정보
    sub_tracks: List[SubInfo] = field(default_factory=list)
    sub_count: int = 0

    def clear(self):
        """초기화"""
        self.filename = ""
        self.file_size = 0
        self.file_duration = 0
        self.size = 0
        self.duration = 0
        self.codec = 0
        self.bitrate = 0
        self.width = 0
        self.height = 0
        self.frame_rate = 0.0
        self.vfr = False
        self.depth = 0
        self.audio_tracks = []
        self.audio_count = 0
        self.sub_tracks = []
        self.sub_count = 0

    @property
    def codec_name(self) -> str:
        """비디오 코덱 이름 반환"""
        codec_names = {
            CODEC_264: "H264(AVC)",
            CODEC_265: "H265(HEVC)",
            CODEC_GIF: "GIF",
            CODEC_WEBP: "WEBP",
            CODEC_AV1: "AV1",
            CODEC_XVID: "XVID",
            CODEC_DX50: "DX50",
            CODEC_VP8: "VP8",
            CODEC_VP9: "VP9",
        }
        return codec_names.get(self.codec, "")

    def to_string(self) -> str:
        """미디어 정보를 문자열로 변환"""
        lines = []

        # 전체 파일 정보
        size_mb = self.file_size / 1024 / 1024
        lines.append(f"[전체]")
        lines.append(f"  파일 용량 : {size_mb:.3f} MB")
        lines.append(f"  길이 : {self.file_duration // 60}분 {self.file_duration % 60}초")
        lines.append(f"  자막 : {self.sub_count}개")

        # 비디오 정보
        vid_size_mb = self.size / 1024 / 1024
        lines.append(f"")
        lines.append(f"[비디오]")
        lines.append(f"  파일 용량 : {vid_size_mb:.3f} MB")
        lines.append(f"  길이 : {self.duration // 60}분 {self.duration % 60}초")
        lines.append(f"  코덱 : {self.codec_name}")
        lines.append(f"  해상도 : {self.width} x {self.height}")
        lines.append(f"  비트레이트 : {self.bitrate} kbps")
        lines.append(f"  프레임레이트 : {self.frame_rate} fps")
        lines.append(f"  프레임모드 : {'VFR (가변)' if self.vfr else 'CFR (고정)'}")
        if self.depth:
            lines.append(f"  비트심도 : {self.depth}bit")

        # 오디오 정보
        for i, audio in enumerate(self.audio_tracks):
            audio_size_mb = audio.size / 1024 / 1024
            lines.append(f"")
            lines.append(f"[오디오 #{i+1}]")
            lines.append(f"  파일 용량 : {audio_size_mb:.3f} MB")
            lines.append(f"  코덱 : {audio.codec_name}")
            lines.append(f"  채널 : {audio.channel}")
            lines.append(f"  비트레이트 : {audio.bitrate} kbps")
            if audio.lang_name:
                lines.append(f"  언어 : {audio.lang_name}")

        return "\n".join(lines)


class MediaInfo:
    """MediaInfo 처리 클래스"""

    # 섹션 상수
    SEC_GENERAL = 1
    SEC_VIDEO = 2
    SEC_IMAGE1 = 3
    SEC_AUDIO_1 = 11
    SEC_SUB = 30

    @staticmethod
    def _parse_mediainfo_exe(filename: str, app_path: str = "") -> Optional[MEDIA_INFO]:
        """mediainfo.exe를 사용한 파싱"""
        mediainfo_exe = "mediainfo"
        if app_path:
            mediainfo_path = os.path.join(app_path, "mediainfo.exe")
            if os.path.exists(mediainfo_path):
                mediainfo_exe = mediainfo_path

        try:
            result = subprocess.run(
                [mediainfo_exe, filename], capture_output=True, text=True, encoding="utf-8", errors="replace"
            )
            info = MediaInfo._parse_mediainfo_output(result.stdout)
            if info:
                info.filename = filename
            return info
        except FileNotFoundError:
            return None
        except Exception as e:
            print(f"MediaInfo 실행 오류: {e}")
            return None

    @staticmethod
    def _parse_mediainfo_output(output: str) -> Optional[MEDIA_INFO]:
        """mediainfo 출력 파싱"""
        info = MEDIA_INFO()
        lines = output.split("\n")

        current_section = 0
        current_audio_idx = -1

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 섹션 변화 감지
            if ":" not in line:
                line_upper = line.upper()
                if line_upper.startswith("GENERAL"):
                    current_section = MediaInfo.SEC_GENERAL
                elif line_upper.startswith("VIDEO"):
                    current_section = MediaInfo.SEC_VIDEO
                elif line_upper.startswith("IMAGE"):
                    current_section = MediaInfo.SEC_IMAGE1
                elif line_upper.startswith("AUDIO"):
                    # Audio # 추출
                    match = re.search(r"#(\d+)", line)
                    if match:
                        num = int(match.group(1))
                        current_audio_idx = num - 1
                    else:
                        if info.audio_count == 0:
                            current_audio_idx = 0
                        else:
                            current_audio_idx = info.audio_count

                    info.audio_count = max(info.audio_count, current_audio_idx + 1)
                    while len(info.audio_tracks) <= current_audio_idx:
                        info.audio_tracks.append(AudioInfo())

                    current_section = MediaInfo.SEC_AUDIO_1 + current_audio_idx
                elif line_upper.startswith("TEXT"):
                    current_section = MediaInfo.SEC_SUB
                continue

            # 키:값 파싱
            parts = line.split(":", 1)
            if len(parts) != 2:
                continue

            name = parts[0].strip()
            value = parts[1].strip()
            value_upper = value.upper()

            # General 섹션
            if current_section == MediaInfo.SEC_GENERAL:
                MediaInfo._parse_general(info, name, value, value_upper)

            # Video 섹션
            elif current_section == MediaInfo.SEC_VIDEO:
                MediaInfo._parse_video(info, name, value, value_upper)

            # Image 섹션
            elif current_section == MediaInfo.SEC_IMAGE1:
                MediaInfo._parse_image(info, name, value, value_upper)

            # Audio 섹션
            elif MediaInfo.SEC_AUDIO_1 <= current_section < MediaInfo.SEC_SUB:
                audio_idx = current_section - MediaInfo.SEC_AUDIO_1
                if audio_idx < len(info.audio_tracks):
                    MediaInfo._parse_audio(info.audio_tracks[audio_idx], name, value, value_upper)

            # 자막 섹션
            elif current_section >= MediaInfo.SEC_SUB:
                name_upper = name.upper()
                if name_upper == "ID":
                    info.sub_tracks.append(SubInfo())
                    info.sub_count += 1
                elif info.sub_tracks:
                    if name_upper == "FORMAT":
                        fmt = value_upper
                        if "SRT" in fmt or "UTF-8" in fmt:
                            info.sub_tracks[-1].codec = "subrip"
                        elif "ASS" in fmt:
                            info.sub_tracks[-1].codec = "ass"
                        elif "SSA" in fmt:
                            info.sub_tracks[-1].codec = "ssa"
                        elif "PGS" in fmt:
                            info.sub_tracks[-1].codec = "hdmv_pgs_subtitle"
                        elif "VOBSUB" in fmt:
                            info.sub_tracks[-1].codec = "dvd_subtitle"
                    elif name_upper == "LANGUAGE":
                        if "KOREAN" in value_upper:
                            info.sub_tracks[-1].lang = LANG_KOREAN
                        elif "ENGLISH" in value_upper:
                            info.sub_tracks[-1].lang = LANG_ENGLISH
                        elif "JAPANES" in value_upper:
                            info.sub_tracks[-1].lang = LANG_JAPANESE
                        elif "CHINESE" in value_upper:
                            info.sub_tracks[-1].lang = LANG_CHINESE
                    elif name_upper == "TITLE":
                        info.sub_tracks[-1].title = value
                        if "SDH" in value_upper:
                            info.sub_tracks[-1].sdh = True
                        if "FORCED" in value_upper:
                            info.sub_tracks[-1].forced = True

        # 오디오 비트레이트 추정
        for audio in info.audio_tracks:
            if audio.bitrate == 0:
                if audio.duration:
                    audio.bitrate = int(audio.size / audio.duration * 0.1193)
                elif info.duration:
                    audio.bitrate = int(audio.size / info.duration * 0.1193)

        return info

    @staticmethod
    def _parse_general(info: MEDIA_INFO, name: str, value: str, value_upper: str):
        """General 섹션 파싱"""
        if name.lower() == "file size":
            info.file_size = MediaInfo._parse_size(value_upper)
        elif name.lower() == "duration":
            info.file_duration = MediaInfo._parse_duration(value_upper)

    @staticmethod
    def _parse_video(info: MEDIA_INFO, name: str, value: str, value_upper: str):
        """Video 섹션 파싱"""
        name_lower = name.lower()

        if name_lower == "stream size":
            info.size = MediaInfo._parse_size(value_upper)
        elif name_lower == "duration":
            info.duration = MediaInfo._parse_duration(value_upper)
        elif name_lower == "format":
            if "AVC" in value_upper:
                info.codec = CODEC_AVC
            elif "HEVC" in value_upper:
                info.codec = CODEC_HEVC
            elif "VP8" in value_upper:
                info.codec = CODEC_VP8
            elif "VP9" in value_upper:
                info.codec = CODEC_VP9
        elif name_lower == "codec id":
            if info.codec == 0:
                if "AVC" in value_upper:
                    info.codec = CODEC_AVC
                elif "HEVC" in value_upper:
                    info.codec = CODEC_HEVC
                elif "XVID" in value_upper:
                    info.codec = CODEC_XVID
                elif "DX50" in value_upper:
                    info.codec = CODEC_DX50
        elif name_lower == "bit rate":
            info.bitrate = MediaInfo._parse_number(value)
        elif name_lower == "frame rate":
            match = re.search(r"([\d.]+)", value)
            if match:
                info.frame_rate = float(match.group(1))
        elif name_lower == "frame rate mode":
            if "VARIABLE" in value_upper:
                info.vfr = True
        elif name_lower == "width":
            info.width = MediaInfo._parse_number(value)
        elif name_lower == "height":
            info.height = MediaInfo._parse_number(value)
        elif name_lower == "bit depth":
            info.depth = MediaInfo._parse_number(value)

    @staticmethod
    def _parse_image(info: MEDIA_INFO, name: str, value: str, value_upper: str):
        """Image 섹션 파싱"""
        name_lower = name.lower()

        if name_lower == "format":
            if "AVC" in value_upper:
                info.codec = CODEC_AVC
            elif "HEVC" in value_upper:
                info.codec = CODEC_HEVC
            elif "GIF" in value_upper:
                info.codec = CODEC_GIF
            elif "WEBP" in value_upper:
                info.codec = CODEC_WEBP
        elif name_lower == "width":
            info.width = MediaInfo._parse_number(value)
        elif name_lower == "height":
            info.height = MediaInfo._parse_number(value)

    @staticmethod
    def _parse_audio(audio: AudioInfo, name: str, value: str, value_upper: str):
        """Audio 섹션 파싱"""
        name_lower = name.lower()

        if name_lower == "format":
            if "DTS" in value_upper:
                audio.codec = A_CODEC_DTS
            elif "AC-3" in value_upper:
                audio.codec = A_CODEC_AC3
            elif "AAC" in value_upper:
                audio.codec = A_CODEC_AAC
            elif "OPUS" in value_upper:
                audio.codec = A_CODEC_OPUS
            elif "MPEG AUDIO" in value_upper:
                audio.codec = A_CODEC_MP3
            elif "OGG" in value_upper or "VORBIS" in value_upper:
                audio.codec = A_CODEC_OGG
            elif "FLAC" in value_upper:
                audio.codec = A_CODEC_FLAC
        elif name_lower == "language":
            if "KOREAN" in value_upper:
                audio.lang = LANG_KOREAN
            elif "ENGLISH" in value_upper:
                audio.lang = LANG_ENGLISH
            elif "JAPANES" in value_upper:
                audio.lang = LANG_JAPANESE
            elif "CHINESE" in value_upper:
                audio.lang = LANG_CHINESE
            elif "SPANISH" in value_upper:
                audio.lang = LANG_SPANISH
            elif "FRENCH" in value_upper:
                audio.lang = LANG_FRENCH
            elif "ITALIAN" in value_upper:
                audio.lang = LANG_ITALIAN
            elif "GERMAN" in value_upper:
                audio.lang = LANG_GERMAN
        elif name_lower == "stream size":
            audio.size = MediaInfo._parse_size(value_upper)
        elif name_lower == "duration":
            audio.duration = MediaInfo._parse_duration(value_upper)
        elif name_lower == "channel(s)":
            audio.channel = MediaInfo._parse_number(value)
        elif name_lower == "bit rate":
            audio.bitrate = MediaInfo._parse_number(value)

    @staticmethod
    def _parse_size(value: str) -> int:
        """파일 크기 파싱"""
        # 32.0 MiB, 1.5 GiB 등
        unit = 1
        if "GIB" in value:
            unit = 3
        elif "MIB" in value:
            unit = 2
        elif "KIB" in value:
            unit = 1
        else:
            unit = 0

        match = re.search(r"([\d.]+)", value)
        if match:
            return int(float(match.group(1)) * (1024**unit))
        return 0

    @staticmethod
    def _parse_duration(value: str) -> int:
        """시간 파싱 (초 단위로 반환)"""
        # "9 min 59 s", "3 h 19 min" 형태
        value_upper = value.upper()

        hours = 0
        minutes = 0
        seconds = 0

        # 시간 추출
        h_match = re.search(r"(\d+)\s*H", value_upper)
        if h_match:
            hours = int(h_match.group(1))

        # 분 추출
        min_match = re.search(r"(\d+)\s*MIN", value_upper)
        if min_match:
            minutes = int(min_match.group(1))

        # 초 추출
        s_match = re.search(r"(\d+)\s*S(?!MIN)", value_upper)
        if s_match:
            seconds = int(s_match.group(1))

        return hours * 3600 + minutes * 60 + seconds

    @staticmethod
    def _parse_number(value: str) -> int:
        """숫자 파싱 (공백 제거)"""
        # "1 640 kb/s" -> 1640
        value_clean = value.replace(" ", "")
        match = re.search(r"(\d+)", value_clean)
        if match:
            return int(match.group(1))
        return 0

    @staticmethod
    def _parse_pymediainfo(filename: str) -> Optional[MEDIA_INFO]:
        """pymediainfo를 사용한 파싱"""
        try:
            from pymediainfo import MediaInfo as PyMediaInfo

            mi = PyMediaInfo.parse(filename)

            info = MEDIA_INFO()
            info.filename = filename

            for track in mi.tracks:
                if track.track_type == "General":
                    if track.file_size:
                        info.file_size = int(track.file_size)
                    if track.duration:
                        info.file_duration = int(float(track.duration) / 1000)

                elif track.track_type == "Video":
                    if track.stream_size:
                        info.size = int(track.stream_size)
                    if track.duration:
                        info.duration = int(float(track.duration) / 1000)
                    if track.bit_rate:
                        info.bitrate = int(track.bit_rate) // 1000
                    if track.width:
                        info.width = int(track.width)
                    if track.height:
                        info.height = int(track.height)
                    if track.frame_rate:
                        info.frame_rate = float(track.frame_rate)
                    if track.bit_depth:
                        info.depth = int(track.bit_depth)
                    if (
                        getattr(track, "frame_rate_mode", None)
                        and "variable" in str(track.frame_rate_mode).lower()
                    ):
                        info.vfr = True

                    # 코덱
                    codec = (track.codec_id or track.format or "").upper()
                    if "AVC" in codec or "H264" in codec or "264" in codec:
                        info.codec = CODEC_AVC
                    elif "HEVC" in codec or "H265" in codec or "265" in codec:
                        info.codec = CODEC_HEVC
                    elif "VP9" in codec:
                        info.codec = CODEC_VP9
                    elif "VP8" in codec:
                        info.codec = CODEC_VP8
                    elif "AV1" in codec:
                        info.codec = CODEC_AV1
                    elif "GIF" in codec:
                        info.codec = CODEC_GIF
                    elif "WEBP" in codec:
                        info.codec = CODEC_WEBP

                elif track.track_type == "Audio":
                    audio = AudioInfo()
                    if track.stream_size:
                        audio.size = int(track.stream_size)
                    if track.duration:
                        audio.duration = int(float(track.duration) / 1000)
                    if track.bit_rate:
                        audio.bitrate = int(track.bit_rate) // 1000
                    if track.channel_s:
                        audio.channel = int(track.channel_s)

                    # 코덱
                    codec = (track.format or "").upper()
                    if "AAC" in codec:
                        audio.codec = A_CODEC_AAC
                    elif "MP3" in codec or "MPEG" in codec:
                        audio.codec = A_CODEC_MP3
                    elif "AC3" in codec or "AC-3" in codec:
                        audio.codec = A_CODEC_AC3
                    elif "DTS" in codec:
                        audio.codec = A_CODEC_DTS
                    elif "VORBIS" in codec or "OGG" in codec:
                        audio.codec = A_CODEC_OGG
                    elif "OPUS" in codec:
                        audio.codec = A_CODEC_OPUS
                    elif "FLAC" in codec:
                        audio.codec = A_CODEC_FLAC

                    # 언어
                    lang = (track.language or "").upper()
                    if "KO" in lang or "KOREAN" in lang:
                        audio.lang = LANG_KOREAN
                    elif "EN" in lang or "ENGLISH" in lang:
                        audio.lang = LANG_ENGLISH
                    elif "JA" in lang or "JAPANES" in lang:
                        audio.lang = LANG_JAPANESE
                    elif "ZH" in lang or "CHINESE" in lang:
                        audio.lang = LANG_CHINESE

                    info.audio_tracks.append(audio)
                    info.audio_count += 1

                elif track.track_type == "Text":
                    sub = SubInfo()
                    sub.codec = (track.format or "").lower()
                    lang = (track.language or "").upper()
                    if "KO" in lang or "KOREAN" in lang:
                        sub.lang = LANG_KOREAN
                    elif "EN" in lang or "ENGLISH" in lang:
                        sub.lang = LANG_ENGLISH
                    elif "JA" in lang or "JAPANES" in lang:
                        sub.lang = LANG_JAPANESE
                    elif "ZH" in lang or "CHINESE" in lang:
                        sub.lang = LANG_CHINESE
                    sub.title = getattr(track, "title", "") or ""
                    if sub.title:
                        title_upper = sub.title.upper()
                        if "SDH" in title_upper:
                            sub.sdh = True
                        if "FORCED" in title_upper:
                            sub.forced = True
                    info.sub_tracks.append(sub)
                    info.sub_count += 1

            return info

        except Exception as e:
            print(f"pymediainfo 파싱 오류: {e}")
            return None

    @staticmethod
    def _parse_ffprobe(filename: str) -> Optional[MEDIA_INFO]:
        """ffprobe를 사용한 파싱 (FFmpeg 포함)"""
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "quiet",
                    "-print_format",
                    "json",
                    "-show_format",
                    "-show_streams",
                    filename,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            data = json.loads(result.stdout)
        except FileNotFoundError:
            print("ffprobe를 찾을 수 없습니다. FFmpeg를 설치하세요.")
            return None
        except Exception as e:
            print(f"ffprobe 실행 오류: {e}")
            return None

        info = MEDIA_INFO()
        info.filename = filename

        fmt = data.get("format", {})
        if fmt.get("size"):
            info.file_size = int(fmt["size"])
        if fmt.get("duration"):
            info.file_duration = int(float(fmt["duration"]))

        codec_map = {
            "h264": CODEC_AVC,
            "avc": CODEC_AVC,
            "hevc": CODEC_HEVC,
            "h265": CODEC_HEVC,
            "vp9": CODEC_VP9,
            "vp8": CODEC_VP8,
            "av1": CODEC_AV1,
            "gif": CODEC_GIF,
            "webp": CODEC_WEBP,
            "xvid": CODEC_XVID,
        }
        audio_codec_map = {
            "aac": A_CODEC_AAC,
            "mp3": A_CODEC_MP3,
            "ac3": A_CODEC_AC3,
            "eac3": A_CODEC_AC3,
            "dts": A_CODEC_DTS,
            "vorbis": A_CODEC_OGG,
            "opus": A_CODEC_OPUS,
            "flac": A_CODEC_FLAC,
            "pcm": A_CODEC_WAV,
        }
        lang_map = {
            "kor": LANG_KOREAN,
            "ko": LANG_KOREAN,
            "eng": LANG_ENGLISH,
            "en": LANG_ENGLISH,
            "jpn": LANG_JAPANESE,
            "ja": LANG_JAPANESE,
            "chi": LANG_CHINESE,
            "zh": LANG_CHINESE,
            "spa": LANG_SPANISH,
            "es": LANG_SPANISH,
            "fre": LANG_FRENCH,
            "fr": LANG_FRENCH,
            "ita": LANG_ITALIAN,
            "it": LANG_ITALIAN,
            "ger": LANG_GERMAN,
            "de": LANG_GERMAN,
        }

        for stream in data.get("streams", []):
            codec_type = stream.get("codec_type", "")
            codec_name = (stream.get("codec_name") or "").lower()

            if codec_type == "video":
                if stream.get("duration"):
                    info.duration = int(float(stream["duration"]))
                elif stream.get("tags", {}).get("DURATION"):
                    info.duration = MediaInfo._parse_ffprobe_duration(stream["tags"]["DURATION"])
                if not info.duration:
                    info.duration = info.file_duration
                if stream.get("bit_rate"):
                    info.bitrate = int(stream["bit_rate"]) // 1000
                info.width = int(stream.get("width", 0))
                info.height = int(stream.get("height", 0))
                if stream.get("r_frame_rate"):
                    parts = stream["r_frame_rate"].split("/")
                    if len(parts) == 2 and int(parts[1]) != 0:
                        info.frame_rate = round(int(parts[0]) / int(parts[1]), 3)
                if stream.get("bits_per_raw_sample"):
                    info.depth = int(stream["bits_per_raw_sample"])

                for key, val in codec_map.items():
                    if key in codec_name:
                        info.codec = val
                        break

                # 비디오 stream size 추정
                if info.bitrate and info.duration:
                    info.size = info.bitrate * 1000 * info.duration // 8

            elif codec_type == "audio":
                audio = AudioInfo()
                if stream.get("duration"):
                    audio.duration = int(float(stream["duration"]))
                elif stream.get("tags", {}).get("DURATION"):
                    audio.duration = MediaInfo._parse_ffprobe_duration(stream["tags"]["DURATION"])
                if stream.get("bit_rate"):
                    audio.bitrate = int(stream["bit_rate"]) // 1000
                audio.channel = int(stream.get("channels", 0))

                for key, val in audio_codec_map.items():
                    if key in codec_name:
                        audio.codec = val
                        break

                lang = (stream.get("tags", {}).get("language") or "").lower()
                for key, val in lang_map.items():
                    if key in lang:
                        audio.lang = val
                        break

                # 오디오 stream size 추정
                if audio.bitrate and audio.duration:
                    audio.size = audio.bitrate * 1000 * audio.duration // 8

                info.audio_tracks.append(audio)
                info.audio_count += 1

            elif codec_type == "subtitle":
                sub = SubInfo()
                sub.codec = codec_name
                lang = (stream.get("tags", {}).get("language") or "").lower()
                for key, val in lang_map.items():
                    if key in lang:
                        sub.lang = val
                        break
                sub.title = stream.get("tags", {}).get("title", "")
                disposition = stream.get("disposition", {})
                sub.sdh = bool(disposition.get("hearing_impaired", 0))
                sub.forced = bool(disposition.get("forced", 0))
                # title에 SDH/forced 힌트가 있으면 플래그 설정
                if sub.title:
                    title_upper = sub.title.upper()
                    if "SDH" in title_upper:
                        sub.sdh = True
                    if "FORCED" in title_upper:
                        sub.forced = True
                info.sub_tracks.append(sub)
                info.sub_count += 1

        # VFR 판단: 첫 30프레임의 duration 비교
        info.vfr = MediaInfo._detect_vfr(filename)

        return info

    @staticmethod
    # VFR - 스터터링(stuttering) 판단
    def _detect_vfr(filename: str) -> bool:
        """첫 30프레임의 packet duration으로 VFR 판단"""
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "packet=duration_time",
                    "-read_intervals",
                    "%+#30",
                    "-v",
                    "quiet",
                    "-of",
                    "csv=p=0",
                    filename,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
            durations = {line.strip() for line in result.stdout.strip().split("\n") if line.strip()}
            return len(durations) > 1
        except Exception:
            return False

    @staticmethod
    def _parse_ffprobe_duration(value: str) -> int:
        """ffprobe DURATION 태그 파싱 (HH:MM:SS.xxx -> 초)"""
        match = re.match(r"(\d+):(\d+):(\d+)", value)
        if match:
            return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + int(match.group(3))
        return 0

    @staticmethod
    def get_info(filename: str, app_path: str = "") -> Optional[MEDIA_INFO]:
        """미디어 정보 획득"""
        if not os.path.exists(filename):
            print(f"{filename} 가 없습니다.")
            return None

        """ try:
            from pymediainfo import MediaInfo as PyMediaInfo

            ret = MediaInfo._parse_pymediainfo(filename)
            print("pymediainfo result:", ret)
            return ret
        except ImportError:
            pass
        except Exception as e:
            print(f"pymediainfo 파싱 오류: {e}") """

        #  ffprobe 시도 (FFmpeg 필수 의존성)
        return MediaInfo._parse_ffprobe(filename)


if __name__ == "__main__":
    # 테스트
    import sys

    if len(sys.argv) > 1:
        info = MediaInfo.get_info(sys.argv[1])
        if info:
            print(info.to_string())
