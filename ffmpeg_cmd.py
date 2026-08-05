"""
FFmpeg 명령어 생성 모듈
C++ CmdGet 함수 포팅
"""

import os
import re
import json
import subprocess
import sys
from typing import Optional
from dataclasses import dataclass

from media_info import (
    MEDIA_INFO,
    CODEC_264,
    CODEC_265,
    CODEC_AV1,
    CODEC_GIF,
    CODEC_WEBP,
    CODEC_AVC,
    CODEC_HEVC,
    CODEC_VP8,
    CODEC_VP9,
    A_CODEC_MP3,
    A_CODEC_AAC,
    A_CODEC_OGG,
    A_CODEC_AC3,
    A_CODEC_DTS,
    A_CODEC_WAV,
    A_CODEC_OPUS,
    A_CODEC_FLAC,
    A_CODEC_MKA,
)
from utils import get_output_filename, divide_name, is_video_file, is_audio_file, is_image_file

# 프로세스 종류 상수
PROC_KIND_EXTRACT_VIDEO = 1
PROC_KIND_EXTRACT_AUDIO = 2
PROC_KIND_CONVERT = 3
PROC_KIND_MERGE = 4
PROC_KIND_MERGE_VA = 5
PROC_KIND_EXTRACT_SUB = 6
PROC_KIND_DELETE_TAGS = 7
PROC_KIND_NORMALIZATION = 8

# 포맷 상수
FORMAT_VIDEO = 1
FORMAT_AUDIO = 2

# 코덱 상수 (출력용)
CODEC_WAV = 6
CODEC_FLAC = 7
CODEC_MP3 = 8
CODEC_OGG = 9
CODEC_OPUS = 10
CODEC_AAC = 11

AUDIO_OUTPUT_CODECS = {CODEC_WAV, CODEC_FLAC, CODEC_MP3, CODEC_OGG, CODEC_OPUS, CODEC_AAC}


class FFmpegCommandBuilder:
    """FFmpeg 명령어 생성 클래스"""

    def __init__(self, settings: dict, media_info: MEDIA_INFO):
        self.settings = dict(settings)  # 크롭 시 내부에서 설정을 덮어쓰므로 복사본 사용
        self.media_info = media_info
        self.format_dest = FORMAT_VIDEO
        self._normalization_output_file = None
        # range_copy는 range가 활성일 때만 유효 (C++ CmdGet 동작과 일치)
        self._range_copy = self.settings.get("range", False) and self.settings.get("range_copy", False)

    def build_command(self, input_file: str) -> str:
        """FFmpeg 명령어 생성"""
        process_kind = self.settings.get("process_kind", PROC_KIND_CONVERT)

        # 영상 추출
        if process_kind == PROC_KIND_EXTRACT_VIDEO:
            return self._build_extract_video_command(input_file)

        # 오디오 추출
        if process_kind == PROC_KIND_EXTRACT_AUDIO:
            return self._build_extract_audio_command(input_file)

        # 자막 추출
        if process_kind == PROC_KIND_EXTRACT_SUB:
            return self._build_extract_sub_command(input_file)

        # 태그 삭제
        if process_kind == PROC_KIND_DELETE_TAGS:
            return self._build_delete_tags_command(input_file)

        # Normalization
        if process_kind == PROC_KIND_NORMALIZATION:
            return self._build_normalization_command(input_file)

        # 합치기 (영상/사진 + 소리)
        if process_kind == PROC_KIND_MERGE_VA:
            return self._build_merge_va_command()

        # 합치기 (동영상 + 동영상)
        if process_kind == PROC_KIND_MERGE:
            return self._build_merge_command(input_file)

        # 일반 변환/추출
        return self._build_convert_command(input_file)

    def _build_extract_video_command(self, input_file: str) -> str:
        """첫 번째 영상 스트림을 원본 코덱 그대로 추출"""
        name, input_ext = divide_name(input_file)
        extension_by_codec = {
            CODEC_AVC: "mp4",
            CODEC_HEVC: "mp4",
            CODEC_AV1: "av1",
            CODEC_VP8: "ivf",
            CODEC_VP9: "ivf",
            CODEC_GIF: "gif",
            CODEC_WEBP: "webp",
        }
        extension = extension_by_codec.get(self.media_info.codec, input_ext.lower())
        output_file = self._get_available_output_file(f"{name}_vid.{extension}")
        range_cmd = self._get_range_command()

        cmd = (
            f'ffmpeg -y {range_cmd["start1"]} -i "{input_file}" '
            f'{range_cmd["start2"]} {range_cmd["end"]} '
            f'-map 0:v:0 -an -sn -dn -c:v copy "{output_file}"'
        )
        return re.sub(r'"[^"]*"|\s{2,}', lambda m: m.group() if m.group().startswith('"') else " ", cmd)

    def _build_extract_audio_command(self, input_file: str) -> str:
        """모든 오디오 트랙을 메타데이터가 포함된 개별 파일로 추출"""
        name, _ = divide_name(input_file)
        range_cmd = self._get_range_command()
        outputs = []

        for i, track in enumerate(self.media_info.audio_tracks):
            filename_parts = [name, f"audio{i + 1:02d}"]
            if track.title:
                title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", track.title).strip(" .")
                if title:
                    filename_parts.append(title)
            if track.bitrate:
                filename_parts.append(f"{track.bitrate}kbps")
            if track.channel:
                filename_parts.append(f"{track.channel}ch")
            if track.lang_name:
                filename_parts.append(track.lang_name.lower())

            output_file = self._get_available_output_file(
                f"{'.'.join(filename_parts)}.{track.extension.lower()}"
            )
            outputs.append(
                f'{range_cmd["start2"]} {range_cmd["end"]} '
                f'-map 0:a:{i} -vn -c:a copy "{output_file}"'
            )

        cmd = f'ffmpeg -y {range_cmd["start1"]} -i "{input_file}" {" ".join(outputs)}'
        return re.sub(r'"[^"]*"|\s{2,}', lambda m: m.group() if m.group().startswith('"') else " ", cmd)

    @staticmethod
    def _get_available_output_file(output_file: str) -> str:
        """기존 파일과 겹치지 않는 출력 파일명 반환"""
        if not os.path.exists(output_file):
            return output_file

        name, ext = os.path.splitext(output_file)
        for i in range(2, 100):
            candidate = f"{name}_({i:02d}){ext}"
            if not os.path.exists(candidate):
                return candidate
        return output_file

    def _build_merge_va_command(self) -> str:
        """영상/사진 + 소리 합치기 명령어"""
        files = self.settings.get("files", [])
        if len(files) < 2:
            return "echo 합치기위해 최소 두개의 파일이 필요합니다."

        vid_file = None
        image_file = None
        audio_file = None

        for f in files:
            if is_video_file(f) and not vid_file:
                vid_file = f
            elif is_image_file(f) and not image_file:
                image_file = f
            elif is_audio_file(f) and not audio_file:
                audio_file = f

        if not audio_file or (not vid_file and not image_file):
            return "echo 영상/사진과 소리 파일이 1개씩 필요합니다."

        if image_file and not vid_file:
            out_file = get_output_filename(image_file, CODEC_264)
            return (
                f'ffmpeg -loop 1 -i "{image_file}" -i "{audio_file}" '
                f'-c:v libx264 -tune stillimage -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p" '
                f'-c:a aac -b:a 160k -shortest "{out_file}"'
            )

        out_file = get_output_filename(vid_file, self.settings.get("output_codec", CODEC_265))

        return f'ffmpeg -i "{vid_file}" -i "{audio_file}" -map 0 -map 1 -c copy -strict -2 "{out_file}"'

    def _build_merge_command(self, input_file: str) -> str:
        """동영상 합치기 명령어 (ts 변환)"""
        name, ext = divide_name(input_file)
        out_file = f"{name}.ts"

        return f'ffmpeg -y -i "{input_file}" -c copy -f mpegts "{out_file}"'

    def _build_extract_sub_command(self, input_file: str) -> list:
        """자막 추출 명령어 (트랙별 개별 명령어 리스트 반환)"""
        if self.media_info.sub_count == 0:
            return []

        name, _ = divide_name(input_file)
        commands = []

        for i in range(self.media_info.sub_count):
            # 자막 트랙 정보에서 확장자 및 접미사 결정
            ext = "srt"
            suffix = ""
            if i < len(self.media_info.sub_tracks):
                track = self.media_info.sub_tracks[i]
                ext = track.extension
                suffix = track.suffix

            # 트랙별 출력 파일명 (예: movie.ko.srt, movie.en.sdh.srt)
            if suffix:
                out_file = f"{name}.{suffix}.{ext}"
            elif self.media_info.sub_count > 1:
                out_file = f"{name}.sub{i}.{ext}"
            else:
                out_file = f"{name}.{ext}"

            cmd = f'ffmpeg -y -i "{input_file}" -map 0:s:{i} -c:s copy "{out_file}"'
            commands.append(cmd)

        return commands

    def _build_delete_tags_command(self, input_file: str) -> str:
        """오디오 파일 태그 삭제 명령어"""
        output_codec = self.settings.get("output_codec", CODEC_265)
        output_file = get_output_filename(input_file, output_codec, self.settings, self.media_info)
        audio_output_codecs = (CODEC_WAV, CODEC_FLAC, CODEC_MP3, CODEC_OGG, CODEC_OPUS, CODEC_AAC)

        codec_cmd = "-c:a copy"
        if output_codec in audio_output_codecs:
            self._determine_format_dest(output_codec)
            audio_codec = self._get_audio_codec(output_codec)
            audio_sample = self.settings.get("audio_sample", 160)
            cbr = self.settings.get("cbr", False)
            audio_quality = self._get_audio_quality_for_track(output_codec, audio_sample, cbr)
            codec_cmd = f"-c:a {audio_codec} {audio_quality}"

        cmd = (
            f'ffmpeg -y -i "{input_file}" -map 0:a {codec_cmd} '
            f'-map_metadata -1 -map_metadata:s:a -1 -map_chapters -1 -bitexact "{output_file}"'
        )
        cmd = re.sub(r'"[^"]*"|\s{2,}', lambda m: m.group() if m.group().startswith('"') else " ", cmd)
        return cmd

    def _get_normalization_config(self, input_file: str) -> tuple:
        output_codec = self.settings.get("output_codec", CODEC_265)
        if self._normalization_output_file is None:
            self._normalization_output_file = get_output_filename(
                input_file, output_codec, self.settings, self.media_info
            )
        output_file = self._normalization_output_file
        true_peak = -1.0

        if output_codec in AUDIO_OUTPUT_CODECS:
            true_peak = -0.6

        return true_peak, output_file

    def get_normalization_output_file(self, input_file: str) -> str:
        """Normalization 출력 파일명"""
        _, output_file = self._get_normalization_config(input_file)
        return output_file

    def _get_normalization_audio_options(self) -> tuple:
        output_codec = self.settings.get("output_codec", CODEC_265)
        audio_sample = self.settings.get("audio_sample", 160)
        cbr = self.settings.get("cbr", False)
        extra_options = []
        bitrate = None
        audio_codec = "aac"

        if output_codec == CODEC_WAV:
            audio_codec = self._get_wav_audio_codec()
        elif output_codec == CODEC_FLAC:
            audio_codec = "flac"
            extra_options.extend(self._get_flac_bit_depth_options())
        elif output_codec == CODEC_MP3 or self.settings.get("mp3", False):
            audio_codec = "libmp3lame"
            if cbr:
                bitrate = f"{audio_sample}k"
            else:
                quality = audio_sample if 1 <= audio_sample <= 9 else 2
                extra_options.extend(["-q:a", str(quality)])
        elif output_codec == CODEC_OGG:
            audio_codec = "libvorbis"
            extra_options.extend(["-q:a", "6"])
        elif output_codec == CODEC_OPUS:
            audio_codec = "libopus"
            bitrate = "160k"
            extra_options.extend(["-vbr", "on"])
        elif output_codec == CODEC_AAC or self.settings.get("aac", True) or self.settings.get("mp4", False):
            audio_codec = "aac"
            extra_options.extend(["-q:a", "1"])
        elif not self.settings.get("mkv", False):
            audio_codec = "aac"
            extra_options.extend(["-q:a", "1"])
        else:
            audio_codec = "libvorbis"
            extra_options.extend(["-q:a", "6"])

        sample_rate = None
        if self.settings.get("sampling_rate_check", True):
            sample_rate = self.settings.get("sampling_rate", 48000)

        audio_channels = 2 if self.settings.get("ch2", False) else None
        video_disable = output_codec in AUDIO_OUTPUT_CODECS
        return audio_codec, bitrate, sample_rate, audio_channels, extra_options, video_disable

    def build_normalization_command_args(self, input_file: str, pre_filter: Optional[str] = None) -> list:
        """ffmpeg-normalize 실행 인자"""
        true_peak, output_file = self._get_normalization_config(input_file)
        audio_codec, bitrate, sample_rate, audio_channels, extra_options, video_disable = (
            self._get_normalization_audio_options()
        )

        args = [
            sys.executable,
            "-m",
            "ffmpeg_normalize",
            input_file,
            "-o",
            output_file,
            "-f",
            "-nt",
            "peak",
            "-t",
            f"{true_peak:g}",
            "-c:a",
            audio_codec,
        ]

        if not video_disable:
            args.extend(["-c:v", "copy"])
        else:
            args.append("-vn")
        if bitrate:
            args.extend(["-b:a", bitrate])
        if sample_rate:
            args.extend(["-ar", str(sample_rate)])
        if audio_channels:
            args.extend(["-ac", str(audio_channels)])
        if extra_options:
            args.extend(["-e", json.dumps(extra_options)])
        if pre_filter:
            args.extend(["-prf", pre_filter])

        return args

    def _build_normalization_command(self, input_file: str) -> str:
        """오디오 Normalization 명령어 미리보기"""
        cmd = subprocess.list2cmdline(self.build_normalization_command_args(input_file))
        return cmd

    def _build_convert_command(self, input_file: str) -> str:
        """변환 명령어 생성"""
        output_codec = self.settings.get("output_codec", CODEC_265)
        process_kind = self.settings.get("process_kind", PROC_KIND_CONVERT)

        # 출력 포맷 결정
        self._determine_format_dest(output_codec)

        # 크롭: 출력은 mp4 고정, 오디오는 복사(mp4 호환이 아니면 자동으로 aac 인코딩)
        if self._get_crop_rect():
            self.settings["crop_applied"] = True  # 출력 파일명에 _cr 추가
            self.settings["mp4"] = True
            self.settings["mkv"] = False
            self.settings["audio_copy"] = True
            self.settings["video_copy"] = False  # 크롭은 재인코딩 필요
            self._range_copy = False

        # 출력 파일명 결정
        output_file = get_output_filename(input_file, output_codec, self.settings, self.media_info)

        # 각 부분 생성
        video_codec_input = self._get_video_codec_input()
        video_cmd = self._get_video_command(process_kind)
        audio_cmd = self._get_audio_command(process_kind, output_file)
        range_cmd = self._get_range_command()
        cfr_cmd = self._get_cfr_command()
        sub_cmd = self._get_subtitle_command(input_file, process_kind, output_file)

        # 복사 모드일 때 video_codec_input 초기화 (C++ CmdGet: sVideoCodecInput = "")
        video_copy = self.settings.get("video_copy", False)
        if video_copy or self._range_copy or process_kind == PROC_KIND_EXTRACT_VIDEO:
            video_codec_input = ""

        # 구간 설정
        range_start1 = range_cmd.get("start1", "")
        range_start2 = range_cmd.get("start2", "")
        range_end = range_cmd.get("end", "")

        # GIF/이미지 처리
        if (
            self.media_info.codec == CODEC_GIF
            or output_codec == CODEC_GIF
            or self.media_info.codec == CODEC_WEBP
            or output_codec == CODEC_WEBP
        ):
            video_cmd = audio_cmd = sub_cmd = ""

        # 최종 명령어 조합
        cmd = f'ffmpeg {video_codec_input} -y {range_start1} -i "{input_file}" {range_start2} {range_end} {video_cmd} {cfr_cmd} {audio_cmd} {sub_cmd} "{output_file}"'

        # 불필요한 공백 제거 (따옴표 안의 공백은 보존)
        cmd = re.sub(r'"[^"]*"|\s{2,}', lambda m: m.group() if m.group().startswith('"') else " ", cmd)
        return cmd

    def _determine_format_dest(self, output_codec: int):
        """출력 포맷 결정"""
        if output_codec in [CODEC_264, CODEC_265, CODEC_AV1, CODEC_GIF, CODEC_WEBP]:
            self.format_dest = FORMAT_VIDEO
        else:
            self.format_dest = FORMAT_AUDIO

    def _get_video_codec_input(self) -> str:
        """입력 비디오 코덱 옵션"""
        gpu = self.settings.get("gpu", False)
        bit10 = self.settings.get("bit10", False)
        p720 = self.settings.get("p720", False)
        p1080 = self.settings.get("p1080", False)

        # GPU 가속 설정 (크롭은 CPU 필터이므로 CUDA 프레임으로 디코딩하지 않음)
        if gpu and (p720 or p1080) and not bit10 and not self._get_crop_rect():
            return "-hwaccel cuda -hwaccel_output_format cuda"

        # 입력 코덱별 설정
        input_codec = self.media_info.codec

        if input_codec == CODEC_GIF:
            return "-f gif"
        elif input_codec == CODEC_WEBP:
            return "-f webp"

        return ""

    def _get_video_command(self, process_kind: int) -> str:
        """비디오 명령어 생성"""
        if self.media_info.width == 0:
            return ""

        if self.format_dest != FORMAT_VIDEO:
            return ""

        if process_kind == PROC_KIND_EXTRACT_AUDIO:
            return ""

        output_codec = self.settings.get("output_codec", CODEC_265)
        gpu = self.settings.get("gpu", False)
        bit10 = self.settings.get("bit10", False)
        video_copy = self.settings.get("video_copy", False)

        # 복사 모드
        if video_copy or self._range_copy or process_kind == PROC_KIND_EXTRACT_VIDEO:
            return "-map 0:v:0 -c:v copy"

        # 출력 코덱 결정
        codec_out = self._get_output_video_codec(output_codec, gpu, bit10)

        # 품질 설정
        quality_cmd = self._get_quality_command(video_copy, process_kind)

        # 해상도 변경
        scale_cmd = self._get_scale_command()

        # FPS 설정
        fps_cmd = ""
        fps = self.settings.get("video_fps", 0)
        if fps > 5:
            fps_cmd = f"-r {fps}"

        # GIF 출력
        if output_codec == CODEC_GIF:
            return "-r 10"

        return f"-map 0:v:0 -c:v {codec_out} {quality_cmd} {scale_cmd} {fps_cmd}"

    def _get_output_video_codec(self, output_codec: int, gpu: bool, bit10: bool) -> str:
        """출력 비디오 코덱 결정"""
        pix_fmt = " -pix_fmt yuv420p" if bit10 else ""

        if output_codec == CODEC_264:
            if gpu:
                return f"h264_nvenc{pix_fmt}"
            else:
                return f"libx264{pix_fmt}"
        elif output_codec == CODEC_265:
            if gpu:
                return f"hevc_nvenc{pix_fmt}"
            else:
                return f"libx265{pix_fmt}"
        elif output_codec == CODEC_AV1:
            if gpu:
                return f"av1_nvenc{pix_fmt}"
            else:
                return f"libaom-av1{pix_fmt}"

        return "copy"

    def _get_quality_command(self, video_copy: bool, process_kind: int) -> str:
        """품질 설정 명령어"""
        if video_copy or self._range_copy or process_kind == PROC_KIND_EXTRACT_VIDEO:
            return ""

        quality_type = self.settings.get("quality_type", "quant")

        if quality_type == "sample":
            sample = self.settings.get("video_sample", 3000)
            return f"-b:v {sample}k"
        else:
            quant = self.settings.get("video_quant", 20)
            return f"-qp {quant}"

    def _get_crop_rect(self):
        """크롭 영역 계산 — (너비, 높이, x, y) 또는 None"""
        if not self.settings.get("crop", False):
            return None

        # 동영상 인코딩 출력일 때만 크롭 적용
        if self.settings.get("output_codec", CODEC_265) not in (CODEC_264, CODEC_265, CODEC_AV1):
            return None
        if self.media_info.codec in (CODEC_GIF, CODEC_WEBP):
            return None

        ratio_w = self.settings.get("crop_w") or 0
        ratio_h = self.settings.get("crop_h") or 0
        src_w = self.media_info.width
        src_h = self.media_info.height

        if ratio_w <= 0 or ratio_h <= 0 or src_w <= 0 or src_h <= 0:
            return None

        # 입력한 시작 좌표를 유지하면서 원본 안에 들어가는 최대 크기 계산
        x = self.settings.get("crop_x")
        y = self.settings.get("crop_y")
        x = None if x is None else max(0, min(x, src_w - 1))
        y = None if y is None else max(0, min(y, src_h - 1))
        available_w = src_w if x is None else src_w - x
        available_h = src_h if y is None else src_h - y

        if available_w * ratio_h > available_h * ratio_w:  # 남은 영역이 더 넓음 → 높이 기준
            crop_w = int(available_h * ratio_w / ratio_h)
            crop_h = available_h
        else:
            crop_w = available_w
            crop_h = int(available_w * ratio_h / ratio_w)
        crop_w -= crop_w % 2
        crop_h -= crop_h % 2
        if crop_w <= 0 or crop_h <= 0:
            return None

        # 시작 위치 미입력 시 가운데 자동 정렬
        if x is None:
            x = (src_w - crop_w) // 2
            x -= x % 2
        if y is None:
            y = (src_h - crop_h) // 2
            y -= y % 2

        return crop_w, crop_h, x, y

    def _get_scale_command(self) -> str:
        """크롭/해상도 변경 명령어"""
        p720 = self.settings.get("p720", False)
        p1080 = self.settings.get("p1080", False)
        gpu = self.settings.get("gpu", False)
        bit10 = self.settings.get("bit10", False)
        crop_rect = self._get_crop_rect()

        filters = []
        src_w = self.media_info.width
        src_h = self.media_info.height

        if crop_rect:
            crop_w, crop_h, crop_x, crop_y = crop_rect
            filters.append(f"crop=w={crop_w}:h={crop_h}:x={crop_x}:y={crop_y}:exact=1")
            src_w, src_h = crop_w, crop_h

        if p720 or p1080:
            # 목표 해상도
            if p1080:
                target_w = 1920
                target_h = 1080
            else:
                target_w = 1280
                target_h = 720

            # 세로 크기 계산 (비율 유지, 짝수로)
            if src_w > 0:
                new_h = round((src_h * target_w) / src_w)
                new_h += new_h % 2  # 짝수로
                target_h = new_h

            # 스케일러 선택 (크롭 시에는 시스템 메모리 프레임이므로 업로드 필요)
            if gpu:
                if bit10 or crop_rect:
                    scaler = "hwupload_cuda,scale_cuda"
                else:
                    scaler = "scale_cuda"
            else:
                scaler = "scale"

            filters.append(f"{scaler}={target_w}:{target_h}")

        if not filters:
            return ""

        chain = ",".join(filters)
        return f'-vf "{chain}"'

    def _get_audio_command(self, process_kind: int, output_file: Optional[str] = None) -> str:
        """오디오 명령어 생성 (C++ CmdGet 오디오 섹션 대응)"""
        if self.media_info.audio_count == 0:
            return ""

        if process_kind == PROC_KIND_EXTRACT_VIDEO:
            return ""

        audio_copy = self.settings.get("audio_copy", False)
        audio_all = self.settings.get("audio_all", True)
        audio_sel = self.settings.get("audio_sel", [])
        output_codec = self.settings.get("output_codec", CODEC_265)
        audio_force_encode = self.settings.get("audio_force_encode", False)
        audio_sample = self.settings.get("audio_sample", 160)
        audio_sample_check = self.settings.get("audio_sample_check", False)
        ch2 = self.settings.get("ch2", False)
        cbr = self.settings.get("cbr", False)
        output_ext = divide_name(output_file)[1].lower() if output_file else ""

        # 복사 모드
        if audio_copy or self._range_copy or process_kind == PROC_KIND_EXTRACT_AUDIO:
            audio_codec = "copy"
            audio_quality = ""

            if process_kind == PROC_KIND_EXTRACT_AUDIO and audio_sel:
                track = audio_sel[0]
                return f"-map 0:a:{track} -c:a copy"

            if output_ext == "mp4" and not self._can_copy_all_audio_to_mp4():
                return "-map 0:a -c:a aac -q:a 1"
            return "-map 0:a -c:a copy"

        # 오디오 코덱 결정
        audio_codec = self._get_audio_codec(output_codec)

        # 트랙별 처리 (C++ for loop 대응)
        audio_parts = []
        n_track_process = 0
        n_channel_max = 2
        n_bits_4ch = 60  # 한 채널당 최소 60k

        for i in range(self.media_info.audio_count):
            # 트랙 선택 필터링
            if not audio_all and audio_sel:
                if i not in audio_sel:
                    continue

            n_track_process += 1
            track_stream = f"-map 0:a:{i}"

            # 채널수
            n_channel = 2
            if i < len(self.media_info.audio_tracks):
                n_channel = self.media_info.audio_tracks[i].channel
            if n_channel < 2:
                n_channel = 2
            if ch2:
                n_channel = 2
            if n_channel_max < n_channel:
                n_channel_max = n_channel

            n_bits_4ch = audio_sample // n_channel if audio_sample > 0 else 60
            if n_bits_4ch < 60:
                n_bits_4ch = 60

            # 트랙 품질 결정 (copy vs encode)
            track_codec = audio_codec
            track_quality = ""

            track_bitrate = 0
            if i < len(self.media_info.audio_tracks):
                track_bitrate = self.media_info.audio_tracks[i].bitrate

            # 인코딩 필요 여부 판단 (C++ 2557-2594 대응)
            # 채널당 비트레이트 > 80kbps 이거나 강제 인코딩이거나 오디오 출력 포맷인 경우
            should_encode = (
                (track_bitrate // n_channel > 80) or audio_force_encode or self.format_dest == FORMAT_AUDIO
            )
            if output_ext == "mp4" and not self._can_copy_audio_track_to_mp4(i):
                should_encode = True

            if should_encode:
                track_quality = self._get_audio_quality_for_track(output_codec, audio_sample, cbr)
            elif output_codec not in [CODEC_WAV, CODEC_FLAC]:
                # 비트레이트 차이 없으면 copy
                track_codec = "copy"
                track_quality = ""

            # 2CH 설정: 소스 채널 > 2일 때만 적용 (C++ 2597-2599)
            ch_cmd = ""
            if ch2 and track_codec != "copy":
                src_channel = 2
                if i < len(self.media_info.audio_tracks):
                    src_channel = self.media_info.audio_tracks[i].channel
                if src_channel > 2:
                    ch_cmd = "-ac 2"

            audio_parts.append(f"{track_stream} -c:a {track_codec} {track_quality} {ch_cmd}")

            if process_kind == PROC_KIND_EXTRACT_AUDIO:
                break  # 오디오 추출은 1개만

        # 5개 초과 트랙 간소화 (C++ 2612-2623)
        if n_track_process > 5:
            track_quality = ""
            if audio_codec != "copy":
                bitrate = n_bits_4ch * n_channel_max
                track_quality = f"-b:a {bitrate}k"
                if ch2 and n_channel_max > 2:
                    track_quality += " -ac 2"
            return f"-map 0:a -c:a {audio_codec} {track_quality}"

        return " ".join(audio_parts)

    def _can_copy_all_audio_to_mp4(self) -> bool:
        """MP4로 그대로 복사 가능한 오디오 트랙인지 확인"""
        return all(self._can_copy_audio_track_to_mp4(i) for i in range(self.media_info.audio_count))

    def _can_copy_audio_track_to_mp4(self, track_index: int) -> bool:
        """MP4 컨테이너에 안전하게 복사 가능한 오디오 코덱인지 확인"""
        if track_index >= len(self.media_info.audio_tracks):
            return False

        return self.media_info.audio_tracks[track_index].codec in {
            A_CODEC_AAC,
            A_CODEC_MP3,
            A_CODEC_AC3,
        }

    def _get_audio_bit_depth(self) -> Optional[int]:
        """사용자가 선택한 오디오 비트 깊이"""
        if not self.settings.get("audio_bit_depth_check", False):
            return None

        bit_depth = self.settings.get("audio_bit_depth", 24)
        if bit_depth in (16, 24, 32):
            return bit_depth
        return 24

    def _get_wav_audio_codec(self) -> str:
        """WAV 비트 깊이에 맞는 PCM 코덱"""
        bit_depth = self._get_audio_bit_depth()
        codec_by_depth = {
            16: "pcm_s16le",
            24: "pcm_s24le",
            32: "pcm_s32le",
        }
        return codec_by_depth.get(bit_depth, "pcm_s16le")

    def _get_flac_bit_depth_options(self) -> list:
        """FLAC 비트 깊이 옵션"""
        bit_depth = self._get_audio_bit_depth() or 24

        sample_fmt = "s16" if bit_depth == 16 else "s32"
        return ["-sample_fmt", sample_fmt, "-bits_per_raw_sample", str(bit_depth)]

    def _get_audio_codec(self, output_codec: int) -> str:
        """오디오 코덱 결정"""
        aac = self.settings.get("aac", True)
        mp3 = self.settings.get("mp3", False)
        mp4 = self.settings.get("mp4", False)
        mkv = self.settings.get("mkv", False)
        ar_opt = ""
        if self.settings.get("sampling_rate_check", True):
            ar = self.settings.get("sampling_rate", 48000)
            ar_opt = f" -ar {ar}"

        if output_codec == CODEC_WAV:
            return f"{self._get_wav_audio_codec()} -vn{ar_opt}"
        elif output_codec == CODEC_FLAC:
            bit_depth_options = " ".join(self._get_flac_bit_depth_options())
            return f"flac -vn{ar_opt} {bit_depth_options}".rstrip()
        elif output_codec == CODEC_MP3:
            return f"libmp3lame -vn{ar_opt}"
        elif output_codec == CODEC_OGG:
            return f"libvorbis -vn{ar_opt}"
        elif output_codec == CODEC_AAC:
            return f"aac -vn{ar_opt}"
        elif output_codec == CODEC_OPUS:
            return f"libopus -vn{ar_opt}"
        elif mp3:
            return "libmp3lame"
        elif aac or mp4 or mkv:
            return "aac"
        else:
            return "libvorbis"

    def _get_audio_quality_for_track(self, output_codec: int, audio_sample: int, cbr: bool) -> str:
        """트랙별 오디오 품질 명령어 (C++ 2565-2587 대응)"""
        mp3 = self.settings.get("mp3", False)

        if output_codec == CODEC_MP3 or (self.format_dest != FORMAT_AUDIO and mp3):
            quality = 2  # 1=225, 2=190, 3=175, 4=165, 5=130
            if 1 <= audio_sample <= 9:
                quality = audio_sample
            if cbr:
                return f"-b:a {audio_sample}k"
            else:
                return f"-q:a {quality}"
        elif output_codec == CODEC_AAC or (
            self.format_dest != FORMAT_AUDIO and self.settings.get("aac", True)
        ):
            return "-q:a 1"  # AAC q1=180k
        elif output_codec == CODEC_OGG:
            return "-q:a 6"  # OGG q6=190k
        elif output_codec == CODEC_OPUS:
            return "-b:a 160k -vbr on"
        elif output_codec in [CODEC_WAV, CODEC_FLAC]:
            return ""
        else:
            return f"-b:a {audio_sample}k"

    def _get_range_command(self) -> dict:
        """구간 설정 명령어"""
        result = {"start1": "", "start2": "", "end": ""}

        if not self.settings.get("range", False):
            return result

        start_time = self.settings.get("start_time", (0, 0, 0))
        end_time = self.settings.get("end_time", (0, 0, 0))
        range_exact = self.settings.get("range_exact", False)

        # 시간 차이 계산
        start_sec = start_time[0] * 3600 + start_time[1] * 60 + start_time[2]
        end_sec = end_time[0] * 3600 + end_time[1] * 60 + end_time[2]
        diff = abs(end_sec - start_sec)

        if diff == 0:
            return result

        start_str = f"-ss {start_time[0]}:{start_time[1]}:{start_time[2]}"
        end_str = f"-t {diff}"

        if range_exact:
            # 정확도 향상 (입력 파일 뒤에 위치)
            result["start2"] = start_str
        else:
            result["start1"] = start_str

        result["end"] = end_str

        return result

    def _get_cfr_command(self) -> str:
        """CFR 변환 명령어"""
        if self.settings.get("cfr", False):
            return "-vsync cfr -fps_mode cfr -af aresample=async=1"
        return ""

    def _get_subtitle_command(
        self, input_file: str, process_kind: int, output_file: Optional[str] = None
    ) -> str:
        """자막 명령어"""
        name, ext = divide_name(input_file)
        ext = ext.lower()
        output_ext = divide_name(output_file)[1].lower() if output_file else ext

        if ext == "mkv" and process_kind == PROC_KIND_CONVERT:
            if self.media_info.sub_count >= 1:
                if output_ext == "mp4":
                    sub_maps = []
                    text_codecs = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt"}
                    for i, track in enumerate(self.media_info.sub_tracks):
                        if track.codec in text_codecs:
                            sub_maps.append(f"-map 0:s:{i}")
                    if sub_maps:
                        return f"{' '.join(sub_maps)} -c:s mov_text"
                    return ""
                return "-map 0:s -c:s copy"
        return ""

    @staticmethod
    def build_merge_all_command(files: list, output_file: str) -> str:
        """합치기 최종 명령어 (ts 파일들 합치기)"""
        if len(files) < 2:
            return ""

        # ts 파일 목록 생성
        ts_files = []
        for f in files:
            name, _ = divide_name(f)
            ts_files.append(f"{name}.ts")

        concat_str = "|".join(ts_files)

        return f'ffmpeg -y -i "concat:{concat_str}" -c copy "{output_file}"'


def codec_to_string(codec: int) -> str:
    """코덱 번호를 문자열로 변환"""
    codec_names = {
        CODEC_264: "H264(AVC)",
        CODEC_265: "H265(HEVC)",
        CODEC_GIF: "GIF",
        CODEC_WEBP: "WEBP",
        CODEC_AV1: "AV1",
        CODEC_WAV: "WAV",
        CODEC_FLAC: "FLAC",
        CODEC_MP3: "MP3",
        CODEC_OGG: "OGG",
        CODEC_OPUS: "OPUS",
        CODEC_AAC: "AAC",
    }
    return codec_names.get(codec, "")
