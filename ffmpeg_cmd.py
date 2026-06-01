"""
FFmpeg 명령어 생성 모듈
C++ CmdGet 함수 포팅
"""

import os
import re
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
from utils import get_output_filename, divide_name, is_video_file, is_audio_file

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


class FFmpegCommandBuilder:
    """FFmpeg 명령어 생성 클래스"""

    def __init__(self, settings: dict, media_info: MEDIA_INFO):
        self.settings = settings
        self.media_info = media_info
        self.format_dest = FORMAT_VIDEO
        self._normalization_output_file = None
        # range_copy는 range가 활성일 때만 유효 (C++ CmdGet 동작과 일치)
        self._range_copy = self.settings.get("range", False) and self.settings.get("range_copy", False)

    def build_command(self, input_file: str, add_pause: bool = False) -> str:
        """FFmpeg 명령어 생성"""
        process_kind = self.settings.get("process_kind", PROC_KIND_CONVERT)

        # 자막 추출
        if process_kind == PROC_KIND_EXTRACT_SUB:
            return self._build_extract_sub_command(input_file)

        # 태그 삭제
        if process_kind == PROC_KIND_DELETE_TAGS:
            return self._build_delete_tags_command(input_file, add_pause)

        # Normalization
        if process_kind == PROC_KIND_NORMALIZATION:
            return self._build_normalization_command(input_file, add_pause)

        # 합치기 (영상 + 소리)
        if process_kind == PROC_KIND_MERGE_VA:
            return self._build_merge_va_command()

        # 합치기 (동영상 + 동영상)
        if process_kind == PROC_KIND_MERGE:
            return self._build_merge_command(input_file)

        # 일반 변환/추출
        return self._build_convert_command(input_file, add_pause)

    def _build_merge_va_command(self) -> str:
        """영상 + 소리 합치기 명령어"""
        files = self.settings.get("files", [])
        if len(files) < 2:
            return "echo 합치기위해 최소 두개의 파일이 필요합니다."

        vid_file = None
        audio_file = None

        for f in files:
            if is_video_file(f) and not vid_file:
                vid_file = f
            elif is_audio_file(f) and not audio_file:
                audio_file = f

        if not vid_file or not audio_file:
            return "echo 영상과 소리 파일이 1개씩 필요합니다."

        out_file = get_output_filename(vid_file, self.settings.get("output_codec", CODEC_265))

        return (
            f'ffmpeg -i "{vid_file}" -i "{audio_file}" -map 0 -map 1 -c copy -strict -2 "{out_file}" & pause'
        )

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

    def _build_delete_tags_command(self, input_file: str, add_pause: bool = False) -> str:
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
        if add_pause:
            cmd += " & pause"
        return cmd

    def _get_normalization_parts(self, input_file: str) -> tuple:
        output_codec = self.settings.get("output_codec", CODEC_265)
        if self._normalization_output_file is None:
            self._normalization_output_file = get_output_filename(
                input_file, output_codec, self.settings, self.media_info
            )
        output_file = self._normalization_output_file
        codec_cmd = ""
        loudnorm_cmd = 'loudnorm=I=-14:TP=-1.0:LRA=11'

        if output_codec in [CODEC_WAV, CODEC_FLAC, CODEC_MP3, CODEC_OGG, CODEC_OPUS, CODEC_AAC]:
            loudnorm_cmd = 'loudnorm=I=-13:TP=-0.8:LRA=8'
            self._determine_format_dest(output_codec)
            audio_codec = self._get_audio_codec(output_codec)
            audio_sample = self.settings.get("audio_sample", 160)
            cbr = self.settings.get("cbr", False)
            audio_quality = self._get_audio_quality_for_track(output_codec, audio_sample, cbr)
            codec_cmd = f"-c:a {audio_codec} {audio_quality}"

        return loudnorm_cmd, codec_cmd, output_file

    def get_normalization_output_file(self, input_file: str) -> str:
        """Normalization 출력 파일명"""
        _, _, output_file = self._get_normalization_parts(input_file)
        return output_file

    def get_normalization_target_tp(self, input_file: str) -> float:
        """Normalization 목표 True Peak"""
        loudnorm_cmd, _, _ = self._get_normalization_parts(input_file)
        match = re.search(r"(?:^|:)TP=([-+]?\d+(?:\.\d+)?)", loudnorm_cmd)
        if not match:
            raise ValueError("loudnorm TP 값을 찾을 수 없습니다.")
        return float(match.group(1))

    def build_normalization_analysis_command(self, input_file: str) -> str:
        """loudnorm 1차 분석 명령어"""
        loudnorm_cmd, _, _ = self._get_normalization_parts(input_file)
        cmd = f'ffmpeg -i "{input_file}" -af "{loudnorm_cmd}:print_format=json" -f null -'
        return re.sub(r'"[^"]*"|\s{2,}', lambda m: m.group() if m.group().startswith('"') else " ", cmd)

    def build_normalization_second_pass_command(
        self, input_file: str, measured: dict, add_pause: bool = False, post_volume_db: float = 0.0
    ) -> str:
        """loudnorm 2차 변환 명령어"""
        loudnorm_cmd, codec_cmd, output_file = self._get_normalization_parts(input_file)
        try:
            target_offset = f"{float(measured['target_offset']):.6f}"
        except ValueError:
            target_offset = measured["target_offset"]
        loudnorm_cmd = (
            f"{loudnorm_cmd}:"
            f"measured_I={measured['input_i']}:"
            f"measured_TP={measured['input_tp']}:"
            f"measured_LRA={measured['input_lra']}:"
            f"measured_thresh={measured['input_thresh']}:"
            f"offset={target_offset}:"
            f"linear=true"
        )
        filter_cmd = loudnorm_cmd
        if post_volume_db:
            filter_cmd = f"{filter_cmd},volume={post_volume_db:.6f}dB"

        cmd = f'ffmpeg -y -i "{input_file}" -af "{filter_cmd}" {codec_cmd} "{output_file}"'
        cmd = re.sub(r'"[^"]*"|\s{2,}', lambda m: m.group() if m.group().startswith('"') else " ", cmd)
        if add_pause:
            cmd += " & pause"
        return cmd

    def _build_normalization_command(self, input_file: str, add_pause: bool = False) -> str:
        """오디오 Normalization 명령어 미리보기"""
        analysis_cmd = self.build_normalization_analysis_command(input_file)
        second_pass_cmd = self.build_normalization_second_pass_command(
            input_file,
            {
                "input_i": "<input_i>",
                "input_tp": "<input_tp>",
                "input_lra": "<input_lra>",
                "input_thresh": "<input_thresh>",
                "target_offset": "<target_offset>",
            },
            add_pause,
        )
        return f"{analysis_cmd}\n{second_pass_cmd}"

    def _build_convert_command(self, input_file: str, add_pause: bool = True) -> str:
        """변환 명령어 생성"""
        output_codec = self.settings.get("output_codec", CODEC_265)
        process_kind = self.settings.get("process_kind", PROC_KIND_CONVERT)

        # 출력 파일명 결정
        output_file = get_output_filename(input_file, output_codec, self.settings, self.media_info)

        # 출력 포맷 결정
        self._determine_format_dest(output_codec)

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
        if add_pause:
            cmd += " & pause"

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

        # GPU 가속 설정
        if gpu and (p720 or p1080) and not bit10:
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

    def _get_scale_command(self) -> str:
        """해상도 변경 명령어"""
        p720 = self.settings.get("p720", False)
        p1080 = self.settings.get("p1080", False)
        gpu = self.settings.get("gpu", False)
        bit10 = self.settings.get("bit10", False)

        if not p720 and not p1080:
            return ""

        # 목표 해상도
        if p1080:
            target_w = 1920
            target_h = 1080
        else:
            target_w = 1280
            target_h = 720

        # 세로 크기 계산 (비율 유지, 짝수로)
        if self.media_info.width > 0:
            new_h = round((self.media_info.height * target_w) / self.media_info.width)
            new_h += new_h % 2  # 짝수로
            target_h = new_h

        # 스케일러 선택
        if gpu:
            if bit10:
                scaler = "hwupload_cuda,scale_cuda"
            else:
                scaler = "scale_cuda"
        else:
            scaler = "scale"

        return f'-vf "{scaler}={target_w}:{target_h}"'

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
            return f"pcm_s16le -vn{ar_opt}"
        elif output_codec == CODEC_FLAC:
            return f"flac -vn{ar_opt} -sample_fmt s16 -bits_per_raw_sample 16"
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

        return f'ffmpeg -y -i "concat:{concat_str}" -c copy "{output_file}" & pause'


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
