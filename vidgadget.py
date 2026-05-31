"""
VidGadget - Video/Audio Conversion Tool using FFmpeg
Python port of the C++ VidGadget application
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText
import subprocess
import threading
import os
import sys
import json
import re

_VERSION_STR = "1.43"
_BUILD_DATE_STR = "2026-03-14"
# 드래그 앤 드롭 지원
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    HAS_DND = True
except ImportError:
    HAS_DND = False
    print("Warning: tkinterdnd2 not installed. Drag and drop will not work.")
    print("Install with: pip install tkinterdnd2")

from media_info import MediaInfo, MEDIA_INFO
from ffmpeg_cmd import FFmpegCommandBuilder
from utils import (
    is_video_file,
    is_audio_file,
    is_tag_delete_audio_file,
    get_extension,
    get_output_filename,
    divide_name,
)

# 프로세스 종류 상수
PROC_KIND_EXTRACT_VIDEO = 1
PROC_KIND_EXTRACT_AUDIO = 2
PROC_KIND_CONVERT = 3
PROC_KIND_MERGE = 4
PROC_KIND_MERGE_VA = 5
PROC_KIND_EXTRACT_SUB = 6
PROC_KIND_DELETE_TAGS = 7

# 코덱 상수
CODEC_UNKNOWN = 0
CODEC_264 = 1  # AVC
CODEC_AVC = 1
CODEC_265 = 2  # HEVC
CODEC_HEVC = 2
CODEC_AV1 = 3
CODEC_GIF = 4
CODEC_WEBP = 5
CODEC_WAV = 6
CODEC_FLAC = 7
CODEC_MP3 = 8
CODEC_OGG = 9
CODEC_OPUS = 10
CODEC_AAC = 11

# 출력 코덱 리스트 인덱스
OUTPUT_CODEC_LIST = [
    ("H.264(AVC)", CODEC_264),
    ("H.265(HEVC)", CODEC_265),
    ("AV1", CODEC_AV1),
    ("GIF", CODEC_GIF),
    ("WEBP", CODEC_WEBP),
    ("WAV", CODEC_WAV),
    ("FLAC", CODEC_FLAC),
    ("MP3", CODEC_MP3),
    ("OGG", CODEC_OGG),
    ("OPUS", CODEC_OPUS),
    ("AAC", CODEC_AAC),
]

INPUT_CODEC_LIST = [
    ("H.264(AVC)", CODEC_264),
    ("H.265(HEVC)", CODEC_265),
    ("GIF", CODEC_GIF),
    ("WEBP", CODEC_WEBP),
]

# 윈도우 파일이름 금지문자 /\:*?"<>|
_UNSAFE_FILENAME_RE = re.compile('[/\\:*?"<>|]')  # [%! '&^` ？＂｜＊＜＞：／＼％！＇＆＾｀


def _sanitize_path(filepath: str) -> str:
    """파일명의 부적절한 문자를 _로 치환하여 영구 변경. 변경 불필요하거나 실패 시 원래 경로 반환."""
    dirpath = os.path.dirname(filepath)
    basename = os.path.basename(filepath)
    safe_name = _UNSAFE_FILENAME_RE.sub("_", basename)
    if safe_name == basename:
        return filepath
    safe_path = os.path.join(dirpath, safe_name)
    try:
        os.rename(filepath, safe_path)
    except OSError:
        if os.path.exists(safe_path):
            return safe_path  # 이전에 이미 변경됨
        return filepath
    return safe_path


class VidGadgetApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"비드가젯 (VidGadget) v{_VERSION_STR} Python")
        self.root.geometry("950x650")
        self.root.minsize(950, 600)

        # 아이콘 설정
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vidgadget_py.ico")
        if os.path.exists(icon_path):
            self.root.iconbitmap(icon_path)

        # 상태 변수들
        self.process_kind = PROC_KIND_CONVERT
        self.selected_video_index = -1
        self.media_info = None
        self.stop_process = False
        self.process_thread = None
        self.current_process = None
        self.process_lock = threading.Lock()
        self.process_button_state_token = 0
        self.app_path = os.path.dirname(os.path.abspath(__file__))
        self.media_info_window_pos = None
        self.media_info_window = None
        self.media_info_text = None

        # UI 변수들
        self.gpu_var = tk.BooleanVar(value=True)
        self.gpu_compat_var = tk.BooleanVar(value=False)
        self.video_copy_var = tk.BooleanVar(value=False)
        self.mp4_var = tk.BooleanVar(value=False)
        self.mkv_var = tk.BooleanVar(value=False)
        self.p720_var = tk.BooleanVar(value=False)
        self.p1080_var = tk.BooleanVar(value=False)
        self.bit10_var = tk.BooleanVar(value=False)
        self.cfr_var = tk.BooleanVar(value=False)

        # 비디오 품질
        self.quality_type = tk.StringVar(value="quant")  # "sample" or "quant"
        self.video_sample_var = tk.StringVar(value="3000")
        self.video_quant_var = tk.StringVar(value="20")
        self.video_fps_var = tk.StringVar(value="")

        # 오디오
        self.audio_all_var = tk.BooleanVar(value=True)
        self.audio_copy_var = tk.BooleanVar(value=False)
        self.audio_sample_check_var = tk.BooleanVar(value=True)
        self.audio_sample_var = tk.StringVar(value="160")
        self.aac_var = tk.BooleanVar(value=True)
        self.mp3_var = tk.BooleanVar(value=False)
        self.ch2_var = tk.BooleanVar(value=False)
        self.cbr_var = tk.BooleanVar(value=False)
        self.audio_force_encode_var = tk.BooleanVar(value=False)
        self.sampling_rate_check_var = tk.BooleanVar(value=True)
        self.sampling_rate_var = tk.StringVar(value="48kHz")

        # 구간
        self.range_var = tk.BooleanVar(value=False)
        self.range_copy_var = tk.BooleanVar(value=True)
        self.range_exact_var = tk.BooleanVar(value=False)
        self.start_hour = tk.StringVar(value="0")
        self.start_min = tk.StringVar(value="0")
        self.start_sec = tk.StringVar(value="0")
        self.end_hour = tk.StringVar(value="0")
        self.end_min = tk.StringVar(value="0")
        self.end_sec = tk.StringVar(value="0")

        # 작업 종류
        self.process_kind_var = tk.IntVar(value=PROC_KIND_CONVERT)

        self.setup_ui()
        self.load_geometry()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.init_prj()

    def init_prj(self):
        """프로젝트 초기화 작업"""
        print("start")
        test_files = [
            # r"D:\_Python\app\vidGadget\bak\rain.wav",
            # r"D:\_Python\app\vidGadget\bak\rain.flac",
            # r"D:\_Python\app\vidGadget\bak\rain.mp3",
            # r"D:\_Python\app\vidGadget\bak\Robot.Dreams.mp4",
        ]
        for test_file in test_files:
            if os.path.isfile(test_file):
                self.file_listbox.insert(tk.END, test_file)

        if self.file_listbox.size() > 0:
            self.file_listbox.selection_set(0)
            self.file_listbox.event_generate("<<ListboxSelect>>")

    def _config_path(self):
        return os.path.join(self.app_path, "vidgadget_config.json")

    def _clamp_geometry(self, x, y, w, h):
        """창 위치/크기를 화면 범위 이내로 보정"""
        scr_w = self.root.winfo_screenwidth()
        scr_h = self.root.winfo_screenheight()
        w = max(400, min(w, scr_w))
        h = max(300, min(h, scr_h))
        x = max(0, min(x, scr_w - w))
        y = max(0, min(y, scr_h - h))
        return x, y, w, h

    def load_geometry(self):
        """저장된 창 위치/크기 복원"""
        try:
            with open(self._config_path(), "r") as f:
                cfg = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, TypeError):
            return

        try:
            x, y, w, h = int(cfg["x"]), int(cfg["y"]), int(cfg["w"]), int(cfg["h"])
            if w > 0 and h > 0:
                x, y, w, h = self._clamp_geometry(x, y, w, h)
                self.root.geometry(f"{w}x{h}+{x}+{y}")
        except (KeyError, TypeError, ValueError):
            pass

        try:
            x, y = int(cfg["media_info_x"]), int(cfg["media_info_y"])
            x, y, _, _ = self._clamp_geometry(x, y, 600, 500)
            self.media_info_window_pos = (x, y)
        except (KeyError, TypeError, ValueError):
            pass

    def save_geometry(self):
        """현재 창 위치/크기 저장"""
        if self.root.state() == "iconic":
            return
        cfg = {}
        geo = self.root.geometry()  # "WxH+X+Y"
        import re

        m = re.match(r"(\d+)x(\d+)([+-]\d+)([+-]\d+)", geo)
        if m:
            w, h, x, y = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            if w <= 0 or h <= 0:
                return
            x, y, w, h = self._clamp_geometry(x, y, w, h)
            cfg = {"w": w, "h": h, "x": x, "y": y}

        if self.media_info_window_pos:
            x, y = self.media_info_window_pos
            x, y, _, _ = self._clamp_geometry(x, y, 600, 500)
            cfg["media_info_x"] = x
            cfg["media_info_y"] = y

        with open(self._config_path(), "w") as f:
            json.dump(cfg, f)

    def remember_media_info_window_pos(self):
        """미디어 정보 창 위치 저장"""
        if not self._is_media_info_window_open():
            return
        geo = self.media_info_window.geometry()
        m = re.match(r"\d+x\d+([+-]\d+)([+-]\d+)", geo)
        if m:
            self.media_info_window_pos = (int(m.group(1)), int(m.group(2)))

    def on_close(self):
        """종료 시 창 위치 저장 후 닫기"""
        self.remember_media_info_window_pos()
        self.save_geometry()
        self.root.destroy()

    # ==================== 툴팁 ====================

    @staticmethod
    def _create_tooltip(widget, text):
        """위젯에 툴팁 추가"""
        tip = {"window": None}

        def show(event):
            if tip["window"]:
                return
            x = widget.winfo_rootx() + 20
            y = widget.winfo_rooty() + widget.winfo_height() + 2
            tw = tk.Toplevel(widget)
            tw.wm_overrideredirect(True)
            tw.wm_geometry(f"+{x}+{y}")
            label = tk.Label(
                tw,
                text=text,
                justify=tk.LEFT,
                background="#ffffe0",
                relief=tk.SOLID,
                borderwidth=1,
                font=("맑은 고딕", 9),
                padx=4,
                pady=2,
            )
            label.pack()
            tip["window"] = tw

        def hide(event):
            if tip["window"]:
                tip["window"].destroy()
                tip["window"] = None

        widget.bind("<Enter>", show)
        widget.bind("<Leave>", hide)

    # ==================== UI 구성 ====================

    def setup_ui(self):
        """UI 구성 — C++ 원본과 동일한 3컬럼 레이아웃"""
        main_frame = ttk.Frame(self.root, padding="5")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 3컬럼 컨텐츠 프레임
        content = ttk.Frame(main_frame)
        content.pack(fill=tk.BOTH, expand=True)

        # 왼쪽 컬럼: 파일 리스트 + FFmpeg 명령행
        left_col = ttk.Frame(content, width=500)  # 원하는 너비 지정
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=(0, 5))  # expand=False로 변경
        left_col.pack_propagate(False)  # 내부 위젯에 의해 크기가 변경되지 않도록
        self.setup_file_list(left_col)
        self.setup_command_display(left_col)

        # 중간 컬럼: 영상 + 영상 품질 + 해상도 + 구간
        mid_col = ttk.Frame(content, width=240)
        mid_col.pack(side=tk.LEFT, fill=tk.Y, padx=5)
        mid_col.pack_propagate(False)
        self.setup_video_options(mid_col)
        self.setup_video_quality(mid_col)
        self.setup_resolution_options(mid_col)
        self.setup_range_options(mid_col)

        # 오른쪽 컬럼: 소리 + 작업 선택
        right_col = ttk.Frame(content, width=180)
        right_col.pack(side=tk.LEFT, fill=tk.Y, padx=(5, 0))
        right_col.pack_propagate(False)
        self.setup_audio_options(right_col)
        self.setup_process_options(right_col)

        # 상태바
        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(status_frame, text="?", width=2, command=self.show_about).pack(side=tk.LEFT)
        self.status_label = ttk.Label(status_frame, text="Build Date " + _BUILD_DATE_STR)
        self.status_label.pack(side=tk.LEFT, padx=10)
        link = ttk.Label(status_frame, text=" ", foreground="blue", cursor="hand2")
        link.pack(side=tk.RIGHT)

    def show_about(self):
        """About 대화상자"""
        messagebox.showinfo("About VidGadget", f"VidGadget v{_VERSION_STR} Python")

    def setup_file_list(self, parent):
        """파일 리스트 UI 구성"""
        # 드래그 안내 텍스트
        ttk.Label(parent, text="미디어를 아래에 드래그 해주세요").pack(anchor=tk.W, pady=(0, 2))

        # 리스트박스
        list_frame = ttk.Frame(parent)
        list_frame.pack(fill=tk.BOTH, expand=True)

        # 수평 스크롤바를 위한 내부 프레임
        inner_frame = ttk.Frame(list_frame)
        inner_frame.pack(fill=tk.BOTH, expand=True)

        self.file_listbox = tk.Listbox(inner_frame, height=8, selectmode=tk.SINGLE, exportselection=False)
        self.file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.file_listbox.bind("<<ListboxSelect>>", self.on_file_select)
        self.file_listbox.bind("<Double-Button-1>", lambda _: self.show_media_info())

        # 리스트 내 드래그로 순서 변경
        self._drag_start_index = None
        self.file_listbox.bind("<Button-1>", self._on_drag_start)
        self.file_listbox.bind("<B1-Motion>", self._on_drag_motion)
        self.file_listbox.bind("<ButtonRelease-1>", self._on_drag_end)

        # 드래그 앤 드롭 설정 (창 전체에서 드롭 가능)
        if HAS_DND:
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind("<<Drop>>", self.on_drop_files)

        # 수직 스크롤바
        v_scrollbar = ttk.Scrollbar(inner_frame, orient=tk.VERTICAL, command=self.file_listbox.yview)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 수평 스크롤바
        h_scrollbar = ttk.Scrollbar(list_frame, orient=tk.HORIZONTAL, command=self.file_listbox.xview)
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)

        # 스크롤바 연결
        self.file_listbox.config(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)

        # 버튼들
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill=tk.X, pady=(4, 0))

        btn_add = ttk.Button(btn_frame, text="파일 추가", command=self.add_file)
        btn_add.pack(side=tk.LEFT, padx=2)
        btn_rm = ttk.Button(btn_frame, text="파일 제거", command=self.remove_file)
        btn_rm.pack(side=tk.LEFT, padx=2)
        btn_clear = ttk.Button(btn_frame, text="전체 삭제", command=self.remove_all_files)
        btn_clear.pack(side=tk.LEFT, padx=2)
        btn_info = ttk.Button(btn_frame, text="파일 정보", command=self.show_media_info)
        btn_info.pack(side=tk.LEFT, padx=2)

        self.video_info_label = ttk.Label(btn_frame, text="", foreground="gray")
        self.video_info_label.pack(side=tk.LEFT, padx=(4, 0))

        self._create_tooltip(btn_add, "변환할 미디어 파일 추가")
        self._create_tooltip(btn_rm, "선택된 파일 제거")
        self._create_tooltip(btn_clear, "파일 리스트 전체 삭제")
        self._create_tooltip(btn_info, "선택된 파일의 멀티미디어 정보 표시")
        self._create_tooltip(self.file_listbox, "마우스 드래그로 순서 변경 가능")

    def setup_video_options(self, parent):
        """영상 옵션 UI — C++ 영상 그룹박스 대응"""
        frame = ttk.LabelFrame(parent, text="영상", padding="5")
        frame.pack(fill=tk.X, pady=(0, 2))

        # 코덱 프레임: 입력(좌) + 출력(우)
        codec_frame = ttk.Frame(frame)
        codec_frame.pack(fill=tk.X)

        # 입력 코덱
        input_frame = ttk.Frame(codec_frame)
        input_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 4))
        ttk.Label(input_frame, text="입력 코덱").pack(anchor=tk.W)
        self.input_codec_listbox = tk.Listbox(input_frame, height=4, width=12, exportselection=False)
        for name, _ in INPUT_CODEC_LIST:
            self.input_codec_listbox.insert(tk.END, name)
        self.input_codec_listbox.pack(fill=tk.Y, expand=True)
        self.input_codec_listbox.selection_set(0)
        self.input_codec_listbox.bind("<<ListboxSelect>>", self.on_option_change)
        self._create_tooltip(
            self.input_codec_listbox, "입력 파일의 비디오 코덱 선택\n자동 감지되므로 보통 변경 불필요"
        )

        # 출력 코덱
        output_frame = ttk.Frame(codec_frame)
        output_frame.pack(side=tk.LEFT, fill=tk.Y)
        ttk.Label(output_frame, text="출력 코덱").pack(anchor=tk.W)
        self.output_codec_listbox = tk.Listbox(output_frame, height=11, width=12, exportselection=False)
        for name, _ in OUTPUT_CODEC_LIST:
            self.output_codec_listbox.insert(tk.END, name)
        self.output_codec_listbox.pack(fill=tk.Y, expand=True)
        self.output_codec_listbox.selection_set(1)  # HEVC 기본 선택
        self.output_codec_listbox.bind("<<ListboxSelect>>", self.on_option_change)
        self._create_tooltip(self.output_codec_listbox, "출력 비디오/오디오 코덱 선택\nH.265(HEVC)가 기본값")

        # 옵션 체크박스들: GPU/복사/포맷을 C++ 배치와 동일하게 2열
        opts_frame = ttk.Frame(frame)
        opts_frame.pack(fill=tk.X, pady=(4, 0))

        # Row 1: GPU 가속 | 복사
        row1 = ttk.Frame(opts_frame)
        row1.pack(fill=tk.X)
        cb_gpu = ttk.Checkbutton(row1, text="GPU 가속", variable=self.gpu_var, command=self.on_gpu_check)
        cb_gpu.pack(side=tk.LEFT)
        cb_copy = ttk.Checkbutton(
            row1, text="복사", variable=self.video_copy_var, command=self.on_option_change
        )
        cb_copy.pack(side=tk.RIGHT)
        self._create_tooltip(cb_gpu, "NVIDIA GPU 하드웨어 인코딩(NVENC) 사용\nGPU가 있으면 10~15배 빠름")
        self._create_tooltip(cb_copy, "비디오 스트림을 인코딩 없이 복사\n빠르지만 코덱/해상도 변경 불가")

        # Row 2: GPU 호환모드 | MP4
        row2 = ttk.Frame(opts_frame)
        row2.pack(fill=tk.X)
        self.gpu_compat_check = ttk.Checkbutton(
            row2, text="  GPU 호환모드", variable=self.gpu_compat_var, command=self.on_option_change
        )
        self.gpu_compat_check.pack(side=tk.LEFT)
        cb_mp4 = ttk.Checkbutton(row2, text="MP4", variable=self.mp4_var, command=self.on_option_change)
        cb_mp4.pack(side=tk.RIGHT)
        self._create_tooltip(self.gpu_compat_check, "GPU 가속 호환 모드\n일부 GPU에서 호환성 문제 시 사용")
        self._create_tooltip(cb_mp4, "출력 컨테이너를 MP4로 강제 지정")

        # Row 3: (빈칸) | MKV
        row3 = ttk.Frame(opts_frame)
        row3.pack(fill=tk.X)
        cb_mkv = ttk.Checkbutton(row3, text="MKV", variable=self.mkv_var, command=self.on_option_change)
        cb_mkv.pack(side=tk.RIGHT)
        self._create_tooltip(cb_mkv, "출력 컨테이너를 MKV로 강제 지정")

    def setup_video_quality(self, parent):
        """영상 품질(용량) UI — C++ 영상 품질 그룹박스 대응"""
        frame = ttk.LabelFrame(parent, text="영상 품질(용량)", padding="5")
        frame.pack(fill=tk.X, pady=2)

        # 비트레이트
        sample_frame = ttk.Frame(frame)
        sample_frame.pack(fill=tk.X)
        rb_sample = ttk.Radiobutton(
            sample_frame,
            text="품질",
            variable=self.quality_type,
            value="sample",
            command=self.on_option_change,
        )
        rb_sample.pack(side=tk.LEFT)
        ttk.Entry(sample_frame, textvariable=self.video_sample_var, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Label(sample_frame, text="kb/s").pack(side=tk.LEFT)
        self._create_tooltip(rb_sample, "비트레이트 기반 품질 설정\n값이 높을수록 고품질/큰 파일")

        # 양자화
        quant_frame = ttk.Frame(frame)
        quant_frame.pack(fill=tk.X)
        rb_quant = ttk.Radiobutton(
            quant_frame,
            text="양자화",
            variable=self.quality_type,
            value="quant",
            command=self.on_option_change,
        )
        rb_quant.pack(side=tk.LEFT)
        ttk.Entry(quant_frame, textvariable=self.video_quant_var, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Label(quant_frame, text="(Default=24)").pack(side=tk.LEFT)
        self._create_tooltip(
            rb_quant, "QP(Quantization Parameter) 기반 품질 설정\n값이 낮을수록 고품질 (기본=24)"
        )

        # FPS
        fps_frame = ttk.Frame(frame)
        fps_frame.pack(fill=tk.X)
        ttk.Label(fps_frame, text="FPS").pack(side=tk.LEFT)
        fps_entry = ttk.Entry(fps_frame, textvariable=self.video_fps_var, width=6)
        fps_entry.pack(side=tk.LEFT, padx=2)
        self._create_tooltip(fps_entry, "출력 프레임 레이트 지정\n비워두면 원본 유지, 5 이하는 무시됨")

    def setup_resolution_options(self, parent):
        """해상도/CFR 옵션 — C++ 영상 품질 그룹 아래 영역 대응"""
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=2)

        # Row 1: 720p | 1080p | 10bit
        row1 = ttk.Frame(frame)
        row1.pack(fill=tk.X)
        cb_720 = ttk.Checkbutton(
            row1, text="720p", variable=self.p720_var, command=lambda: self.on_resolution_check("720")
        )
        cb_720.pack(side=tk.LEFT)
        cb_1080 = ttk.Checkbutton(
            row1, text="1080p", variable=self.p1080_var, command=lambda: self.on_resolution_check("1080")
        )
        cb_1080.pack(side=tk.LEFT)
        cb_10bit = ttk.Checkbutton(
            row1, text="픽셀포멧호환", variable=self.bit10_var, command=self.on_option_change
        )
        cb_10bit.pack(side=tk.LEFT)
        self._create_tooltip(cb_720, "출력 해상도를 1280x720으로 변경")
        self._create_tooltip(cb_1080, "출력 해상도를 1920x1080으로 변경")
        self._create_tooltip(cb_10bit, "10bit → 8bit(yuv420p) 픽셀 포맷 변환\nGPU 디코딩 호환성 향상")

        # Row 2: CFR
        row2 = ttk.Frame(frame)
        row2.pack(fill=tk.X)
        cb_cfr = ttk.Checkbutton(
            row2, text="고정프레임", variable=self.cfr_var, command=self.on_option_change
        )
        cb_cfr.pack(side=tk.LEFT)
        self._create_tooltip(cb_cfr, "VFR(가변 프레임) → CFR(고정 프레임) 변환\n편집 프로그램 호환성 향상")

    def setup_range_options(self, parent):
        """구간 설정 UI — C++ 구간 그룹박스 대응"""
        frame = ttk.LabelFrame(parent, text="구간", padding="5")
        frame.pack(fill=tk.X, pady=2)

        cb_range = ttk.Checkbutton(
            frame, text="구간 설정 적용", variable=self.range_var, command=self.on_range_check
        )
        cb_range.pack(anchor=tk.W)
        self._create_tooltip(cb_range, "시작~끝 구간만 추출")

        # 시간 입력: 시작 H:M:S ~ 끝 H:M:S (한 줄)
        time_frame = ttk.Frame(frame)
        time_frame.pack(fill=tk.X, pady=2)
        ttk.Entry(time_frame, textvariable=self.start_hour, width=3).pack(side=tk.LEFT)
        ttk.Label(time_frame, text=":").pack(side=tk.LEFT)
        ttk.Entry(time_frame, textvariable=self.start_min, width=3).pack(side=tk.LEFT)
        ttk.Label(time_frame, text=":").pack(side=tk.LEFT)
        ttk.Entry(time_frame, textvariable=self.start_sec, width=3).pack(side=tk.LEFT)
        ttk.Label(time_frame, text=" ~ ").pack(side=tk.LEFT)
        ttk.Entry(time_frame, textvariable=self.end_hour, width=3).pack(side=tk.LEFT)
        ttk.Label(time_frame, text=":").pack(side=tk.LEFT)
        ttk.Entry(time_frame, textvariable=self.end_min, width=3).pack(side=tk.LEFT)
        ttk.Label(time_frame, text=":").pack(side=tk.LEFT)
        ttk.Entry(time_frame, textvariable=self.end_sec, width=3).pack(side=tk.LEFT)

        self.range_copy_check = ttk.Checkbutton(
            frame,
            text="인코딩 안함(복사)",
            variable=self.range_copy_var,
            state=tk.DISABLED,
            command=self.on_option_change,
        )
        self.range_copy_check.pack(anchor=tk.W)
        self._create_tooltip(
            self.range_copy_check, "구간 추출 시 인코딩 없이 복사\n빠르지만 시작점이 키프레임 기준"
        )

        self.range_exact_check = ttk.Checkbutton(
            frame,
            text="정확도 향상(호환성 떨어짐)",
            variable=self.range_exact_var,
            state=tk.DISABLED,
            command=self.on_option_change,
        )
        self.range_exact_check.pack(anchor=tk.W)
        self._create_tooltip(
            self.range_exact_check, "구간 시작점을 정확히 자름\n-ss를 입력 뒤에 배치하여 정밀도 향상"
        )

    def setup_audio_options(self, parent):
        """오디오 옵션 UI — C++ 소리 그룹박스 대응"""
        frame = ttk.LabelFrame(parent, text="소리", padding="5")
        frame.pack(fill=tk.X, pady=(0, 2))

        # 스트림 리스트
        stream_label = ttk.Frame(frame)
        stream_label.pack(fill=tk.X)
        ttk.Label(stream_label, text="스트림").pack(side=tk.LEFT)
        self.audio_stream_count_label = ttk.Label(stream_label, text="")
        self.audio_stream_count_label.pack(side=tk.LEFT, padx=4)

        self.audio_stream_listbox = tk.Listbox(frame, height=4, selectmode=tk.MULTIPLE, exportselection=False)
        self.audio_stream_listbox.pack(fill=tk.X)
        self.audio_stream_listbox.bind("<<ListboxSelect>>", self.on_option_change)
        self._create_tooltip(self.audio_stream_listbox, "오디오 트랙 선택\n여러 개 선택 가능 (Ctrl+클릭)")

        # 전체 오디오 트랙
        cb_all = ttk.Checkbutton(
            frame, text="전체 오디오 트랙", variable=self.audio_all_var, command=self.on_option_change
        )
        cb_all.pack(anchor=tk.W)
        self._create_tooltip(cb_all, "모든 오디오 트랙을 포함")

        # 오디오 복사
        cb_acopy = ttk.Checkbutton(
            frame,
            text="오디오 복사(인코딩 없음)",
            variable=self.audio_copy_var,
            command=self.on_audio_copy_check,
        )
        cb_acopy.pack(anchor=tk.W)
        self._create_tooltip(cb_acopy, "오디오를 인코딩 없이 그대로 복사\n빠르지만 코덱/비트레이트 변경 불가")

        # 음질
        sample_frame = ttk.Frame(frame)
        sample_frame.pack(fill=tk.X)
        cb_sample = ttk.Checkbutton(
            sample_frame, text="음질", variable=self.audio_sample_check_var, command=self.on_option_change
        )
        cb_sample.pack(side=tk.LEFT)
        self.audio_sample_entry = ttk.Entry(sample_frame, textvariable=self.audio_sample_var, width=5)
        self.audio_sample_entry.pack(side=tk.LEFT, padx=2)
        ttk.Label(sample_frame, text="kb/s").pack(side=tk.LEFT)
        self._create_tooltip(cb_sample, "오디오 비트레이트 직접 지정")

        # Sampling Rate
        sr_frame = ttk.Frame(frame)
        sr_frame.pack(fill=tk.X)
        cb_sr = ttk.Checkbutton(
            sr_frame, text="Sample", variable=self.sampling_rate_check_var, command=self.on_option_change
        )
        cb_sr.pack(side=tk.LEFT)
        self.sr_combo = ttk.Combobox(
            sr_frame,
            textvariable=self.sampling_rate_var,
            values=["44.1kHz", "48kHz"],
            width=7,
            state="readonly",
        )
        self.sr_combo.pack(side=tk.LEFT, padx=2)
        self.sr_combo.bind("<<ComboboxSelected>>", self.on_option_change)
        self._create_tooltip(cb_sr, "체크 시 오디오 샘플링 레이트 변경\n해제 시 원본 샘플링 레이트 유지")
        self._create_tooltip(self.sr_combo, "오디오 샘플링 레이트 설정\n44.1kHz(CD 음질) / 48kHz(기본)")

        # 2채널 변환 | CBR
        row_ch = ttk.Frame(frame)
        row_ch.pack(fill=tk.X)
        cb_2ch = ttk.Checkbutton(
            row_ch, text="2채널 변환", variable=self.ch2_var, command=self.on_option_change
        )
        cb_2ch.pack(side=tk.LEFT)
        cb_cbr = ttk.Checkbutton(row_ch, text="CBR", variable=self.cbr_var, command=self.on_option_change)
        cb_cbr.pack(side=tk.LEFT, padx=(10, 0))
        self._create_tooltip(cb_2ch, "다채널(5.1/7.1) → 스테레오(2CH) 다운믹스\n채널이 2개 이하이면 무시됨")
        self._create_tooltip(cb_cbr, "CBR(고정 비트레이트) 인코딩\n체크 해제 시 VBR(가변 비트레이트)")

        # AAC | MP3
        row_codec = ttk.Frame(frame)
        row_codec.pack(fill=tk.X)
        cb_aac = ttk.Checkbutton(row_codec, text="AAC", variable=self.aac_var, command=self.on_option_change)
        cb_aac.pack(side=tk.LEFT)
        cb_mp3 = ttk.Checkbutton(row_codec, text="MP3", variable=self.mp3_var, command=self.on_option_change)
        cb_mp3.pack(side=tk.LEFT, padx=(10, 0))
        self._create_tooltip(cb_aac, "오디오 코덱을 AAC로 지정\nMP4 컨테이너에 적합")
        self._create_tooltip(cb_mp3, "오디오 코덱을 MP3(libmp3lame)로 지정")

        # 강제 인코딩
        cb_force = ttk.Checkbutton(
            frame, text="강제 인코딩", variable=self.audio_force_encode_var, command=self.on_option_change
        )
        cb_force.pack(anchor=tk.W)
        self._create_tooltip(
            cb_force,
            "원본 비트레이트가 낮아도 강제 재인코딩\n체크 해제 시 비트레이트 차이가 적으면 자동 복사",
        )

    def setup_process_options(self, parent):
        """작업 선택 UI — C++ 작업 선택 그룹박스 대응"""
        frame = ttk.LabelFrame(parent, text="작업 선택", padding="5")
        frame.pack(fill=tk.X, pady=2)

        # 라디오 버튼들 세로 배치 (C++ 원본과 동일)
        rb_dt = ttk.Radiobutton(
            frame,
            text="태그 삭제",
            variable=self.process_kind_var,
            value=PROC_KIND_DELETE_TAGS,
            command=self.on_process_change,
        )
        rb_dt.pack(anchor=tk.W)
        rb_ev = ttk.Radiobutton(
            frame,
            text="영상 추출",
            variable=self.process_kind_var,
            value=PROC_KIND_EXTRACT_VIDEO,
            command=self.on_process_change,
        )
        rb_ev.pack(anchor=tk.W)
        rb_ea = ttk.Radiobutton(
            frame,
            text="오디오만 추출",
            variable=self.process_kind_var,
            value=PROC_KIND_EXTRACT_AUDIO,
            command=self.on_process_change,
        )
        rb_ea.pack(anchor=tk.W)
        rb_es = ttk.Radiobutton(
            frame,
            text="자막 추출",
            variable=self.process_kind_var,
            value=PROC_KIND_EXTRACT_SUB,
            command=self.on_process_change,
        )
        rb_es.pack(anchor=tk.W)
        rb_m = ttk.Radiobutton(
            frame,
            text="합치기(동영상+동영상..)",
            variable=self.process_kind_var,
            value=PROC_KIND_MERGE,
            command=self.on_process_change,
        )
        rb_m.pack(anchor=tk.W)
        rb_mva = ttk.Radiobutton(
            frame,
            text="합치기(영상+소리)",
            variable=self.process_kind_var,
            value=PROC_KIND_MERGE_VA,
            command=self.on_process_change,
        )
        rb_mva.pack(anchor=tk.W)
        rb_c = ttk.Radiobutton(
            frame,
            text="변환",
            variable=self.process_kind_var,
            value=PROC_KIND_CONVERT,
            command=self.on_process_change,
        )
        rb_c.pack(anchor=tk.W)

        self._create_tooltip(rb_dt, "오디오 파일의 메타데이터, 가사, 챕터, 커버 이미지 제거")
        self._create_tooltip(rb_ev, "비디오 스트림만 추출 (오디오 제외)")
        self._create_tooltip(rb_ea, "오디오 스트림만 추출 (비디오 제외)")
        self._create_tooltip(rb_es, "자막 스트림 추출 (SRT, ASS 등)")
        self._create_tooltip(rb_m, "여러 동영상을 하나로 합치기\nTS 변환 후 concat 방식")
        self._create_tooltip(rb_mva, "별도의 영상 파일과 소리 파일을 합치기")
        self._create_tooltip(rb_c, "코덱/해상도/품질 변환 (기본 모드)")

        self.process_button = tk.Button(frame, text="작업 실행", command=self.on_process_button)
        self.process_button_default_fg = self.process_button.cget("fg")
        self.process_button.pack(pady=(8, 0), fill=tk.X)

    def setup_command_display(self, parent):
        """명령어 표시 영역 — C++ FFmpeg 명령행 에디트 대응"""
        ttk.Label(parent, text="FFmpeg 명령행").pack(anchor=tk.W, pady=(8, 2))

        self.cmd_text = ScrolledText(parent, height=5, wrap=tk.WORD)
        self.cmd_text.pack(fill=tk.BOTH, expand=True)

    # ==================== 이벤트 핸들러 ====================

    def add_file(self):
        """파일 추가"""
        filetypes = [
            ("Video files", "*.mp4 *.mkv *.avi *.webm *.mpg *.mov *.wmv"),
            ("Audio files", "*.mp3 *.aac *.wav *.flac *.ogg *.opus"),
            ("All files", "*.*"),
        ]
        filenames = filedialog.askopenfilenames(filetypes=filetypes)
        for filename in filenames:
            self.file_listbox.insert(tk.END, filename)

    def remove_file(self):
        """파일 제거"""
        selection = self.file_listbox.curselection()
        if selection:
            self.file_listbox.delete(selection[0])
        elif self.file_listbox.size() > 0:
            self.file_listbox.delete(0)

    def remove_all_files(self):
        """전체 파일 삭제"""
        self.file_listbox.delete(0, tk.END)
        self.selected_video_index = -1
        self.media_info = None
        self.cmd_text.delete(1.0, tk.END)

    def _on_drag_start(self, event):
        """리스트 내 드래그 시작"""
        self._drag_start_index = self.file_listbox.nearest(event.y)

    def _on_drag_motion(self, event):
        """리스트 내 드래그 중 — 항목 위치 교환"""
        if self._drag_start_index is None:
            return
        cur_index = self.file_listbox.nearest(event.y)
        if cur_index != self._drag_start_index:
            # 항목 교환
            item = self.file_listbox.get(self._drag_start_index)
            self.file_listbox.delete(self._drag_start_index)
            self.file_listbox.insert(cur_index, item)
            self.file_listbox.selection_clear(0, tk.END)
            self.file_listbox.selection_set(cur_index)
            self._drag_start_index = cur_index

    def _on_drag_end(self, event):
        """리스트 내 드래그 종료"""
        self._drag_start_index = None

    def on_drop_files(self, event):
        """파일 드롭 이벤트 핸들러"""
        # 드롭된 파일 경로 파싱
        files = self.parse_drop_data(event.data)
        for filepath in files:
            if os.path.isfile(filepath):
                # 중복 방지
                existing = list(self.file_listbox.get(0, tk.END))
                if filepath not in existing:
                    self.file_listbox.insert(tk.END, filepath)

        # 첫번째 파일 선택
        if self.file_listbox.size() > 0:
            self.file_listbox.selection_clear(0, tk.END)
            self.file_listbox.selection_set(0)
            self.file_listbox.event_generate("<<ListboxSelect>>")

    def parse_drop_data(self, data: str) -> list:
        """드롭 데이터 파싱 (Windows/Linux 대응)"""
        files = []
        # Windows에서는 {} 로 묶인 경로가 올 수 있음 (공백 포함 경로)
        if "{" in data:
            import re

            # {path1} {path2} 형태 파싱
            matches = re.findall(r"\{([^}]+)\}", data)
            for match in matches:
                files.append(match)
            # {} 없는 부분도 처리
            remaining = re.sub(r"\{[^}]+\}", "", data).strip()
            if remaining:
                files.extend(remaining.split())
        else:
            # 공백으로 분리된 경로
            files = data.split()

        # 경로 정리
        cleaned = []
        for f in files:
            f = f.strip()
            if f:
                # Windows 경로 정규화
                f = f.replace("/", "\\")
                cleaned.append(f)

        return cleaned

    def on_file_select(self, event):
        print("file selected")
        """파일 선택 이벤트"""
        selection = self.file_listbox.curselection()
        if not selection:
            return

        self.selected_video_index = selection[0]
        filename = self.file_listbox.get(selection[0])

        # 미디어 정보 읽기
        self.media_info = MediaInfo.get_info(filename, self.app_path)

        if self.media_info:
            # 입력 코덱 업데이트
            self.input_codec_listbox.selection_clear(0, tk.END)
            if self.media_info.codec == CODEC_264:
                self.input_codec_listbox.selection_set(0)
            elif self.media_info.codec == CODEC_265:
                self.input_codec_listbox.selection_set(1)
            elif self.media_info.codec == CODEC_GIF:
                self.input_codec_listbox.selection_set(2)

            # 오디오 스트림 업데이트
            self.audio_stream_listbox.delete(0, tk.END)
            for i, audio in enumerate(self.media_info.audio_tracks):
                info = f"{audio.bitrate}k,CH={audio.channel},{audio.lang},{audio.codec_name}"
                self.audio_stream_listbox.insert(tk.END, info)
            if self.media_info.audio_count > 0:
                self.audio_stream_listbox.selection_set(0)
            self.audio_stream_count_label.config(text=str(self.media_info.audio_count))

            # 비디오 정보 라벨 업데이트
            mi = self.media_info
            parts = []
            """ if mi.codec_name:
                parts.append(mi.codec_name)
            if mi.width and mi.height:
                parts.append(f"{mi.width}x{mi.height}")
            if mi.frame_rate:
                parts.append(f"{mi.frame_rate}fps") """
            if mi.vfr:
                parts.append("V")
            self.video_info_label.config(text=" ".join(parts))

            # 구간 끝시간 설정
            duration = self.media_info.duration
            h = duration // 3600
            m = (duration % 3600) // 60
            s = duration % 60
            self.end_hour.set(str(h))
            self.end_min.set(str(m))
            self.end_sec.set(str(s))
        else:
            self.video_info_label.config(text="")

        if self._is_media_info_window_open():
            self.update_media_info_window(filename, self.media_info)

        self.update_command()

    def _is_media_info_window_open(self):
        return self.media_info_window is not None and self.media_info_window.winfo_exists()

    def update_media_info_window(self, filename, info):
        """열려 있는 미디어 정보 창 내용 갱신"""
        if not self._is_media_info_window_open() or self.media_info_text is None:
            return

        if info:
            msg = info.to_string()
        else:
            msg = f"{filename}\n\n미디어 정보를 읽을 수 없습니다."

        self.media_info_text.config(state=tk.NORMAL)
        self.media_info_text.delete("1.0", tk.END)
        self.media_info_text.insert(tk.END, msg)
        self.media_info_text.config(state=tk.DISABLED)

    def show_media_info(self):
        """미디어 정보 표시"""
        selection = self.file_listbox.curselection()
        if not selection:
            messagebox.showinfo("알림", "파일을 선택하세요.")
            return

        filename = self.file_listbox.get(selection[0])
        info = self.media_info
        if info is None:
            info = MediaInfo.get_info(filename, self.app_path)

        if info:
            print("info", info)
            msg = info.to_string()
            print("msg", msg)
            if self._is_media_info_window_open():
                self.update_media_info_window(filename, info)
                self.media_info_window.lift()
                self.media_info_window.focus_force()
                return

            info_window = tk.Toplevel(self.root)
            self.media_info_window = info_window
            info_window.title("미디어 정보")
            if self.media_info_window_pos:
                x, y = self.media_info_window_pos
                info_window.geometry(f"600x500+{x}+{y}")
            else:
                info_window.geometry("600x500")
            info_window.attributes("-topmost", True)

            def close_info_window():
                self.remember_media_info_window_pos()
                self.save_geometry()
                self.media_info_window = None
                self.media_info_text = None
                info_window.destroy()

            text = ScrolledText(info_window, wrap=tk.WORD)
            self.media_info_text = text
            text.insert(tk.END, msg)
            text.config(state=tk.DISABLED)
            text.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 4))

            close_btn = ttk.Button(info_window, text="닫기", command=close_info_window)
            close_btn.pack(pady=(0, 8))
            info_window.protocol("WM_DELETE_WINDOW", close_info_window)
        else:
            messagebox.showerror("오류", "미디어 정보를 읽을 수 없습니다.")

    def on_gpu_check(self):
        """GPU 체크박스 이벤트"""
        if self.gpu_var.get():
            self.gpu_compat_check.config(state=tk.NORMAL)
        else:
            self.gpu_compat_check.config(state=tk.DISABLED)
        self.update_command()

    def on_audio_copy_check(self):
        """오디오 복사 체크박스 이벤트"""
        if self.audio_copy_var.get():
            self.audio_sample_entry.config(state=tk.DISABLED)
        else:
            self.audio_sample_entry.config(state=tk.NORMAL)
        self.update_command()

    def on_range_check(self):
        """구간 설정 체크박스 이벤트"""
        if self.range_var.get():
            self.range_copy_check.config(state=tk.NORMAL)
            self.range_exact_check.config(state=tk.NORMAL)
        else:
            self.range_copy_check.config(state=tk.DISABLED)
            self.range_exact_check.config(state=tk.DISABLED)
        self.update_command()

    def on_resolution_check(self, res):
        """해상도 체크박스 이벤트"""
        if res == "720" and self.p720_var.get():
            self.p1080_var.set(False)
        elif res == "1080" and self.p1080_var.get():
            self.p720_var.set(False)
        self.update_command()

    def on_option_change(self, *args):
        """일반 옵션 변경 이벤트"""
        self.update_command()

    def on_process_change(self):
        """작업 종류 변경 이벤트"""
        self.process_kind = self.process_kind_var.get()
        print(self.process_kind)
        self.update_command()

    def get_settings(self) -> dict:
        """현재 설정값들을 딕셔너리로 반환"""
        # 파일 목록
        files = [self.file_listbox.get(i) for i in range(self.file_listbox.size())]

        # 선택된 입력/출력 코덱
        input_sel = self.input_codec_listbox.curselection()
        input_codec = INPUT_CODEC_LIST[input_sel[0]][1] if input_sel else CODEC_264

        output_sel = self.output_codec_listbox.curselection()
        output_codec = OUTPUT_CODEC_LIST[output_sel[0]][1] if output_sel else CODEC_265

        # 선택된 오디오 트랙
        audio_sel = list(self.audio_stream_listbox.curselection())

        return {
            "files": files,
            "input_codec": input_codec,
            "output_codec": output_codec,
            "gpu": self.gpu_var.get(),
            "gpu_compat": self.gpu_compat_var.get(),
            "video_copy": self.video_copy_var.get(),
            "mp4": self.mp4_var.get(),
            "mkv": self.mkv_var.get(),
            "p720": self.p720_var.get(),
            "p1080": self.p1080_var.get(),
            "bit10": self.bit10_var.get(),
            "cfr": self.cfr_var.get(),
            "quality_type": self.quality_type.get(),
            "video_sample": int(self.video_sample_var.get() or 3000),
            "video_quant": int(self.video_quant_var.get() or 20),
            "video_fps": float(self.video_fps_var.get()) if self.video_fps_var.get() else 0,
            "audio_all": self.audio_all_var.get(),
            "audio_copy": self.audio_copy_var.get(),
            "audio_sample_check": self.audio_sample_check_var.get(),
            "audio_sample": int(self.audio_sample_var.get() or 160),
            "audio_sel": audio_sel,
            "aac": self.aac_var.get(),
            "mp3": self.mp3_var.get(),
            "ch2": self.ch2_var.get(),
            "cbr": self.cbr_var.get(),
            "audio_force_encode": self.audio_force_encode_var.get(),
            "sampling_rate_check": self.sampling_rate_check_var.get(),
            "sampling_rate": 44100 if self.sampling_rate_var.get() == "44.1kHz" else 48000,
            "range": self.range_var.get(),
            "range_copy": self.range_copy_var.get(),
            "range_exact": self.range_exact_var.get(),
            "start_time": (
                int(self.start_hour.get() or 0),
                int(self.start_min.get() or 0),
                int(self.start_sec.get() or 0),
            ),
            "end_time": (
                int(self.end_hour.get() or 0),
                int(self.end_min.get() or 0),
                int(self.end_sec.get() or 0),
            ),
            "process_kind": self.process_kind,
        }

    def update_command(self):
        """명령어 업데이트"""
        selection = self.file_listbox.curselection()
        if selection:
            idx = selection[0]
        elif self.selected_video_index >= 0 and self.selected_video_index < self.file_listbox.size():
            idx = self.selected_video_index
        else:
            return

        filename = self.file_listbox.get(idx)
        settings = self.get_settings()

        if settings["process_kind"] == PROC_KIND_DELETE_TAGS and not is_tag_delete_audio_file(filename):
            self.cmd_text.delete(1.0, tk.END)
            self.cmd_text.insert(tk.END, "echo 태그 삭제는 mp3, flac, wav, opus, aac, ogg 파일만 지원합니다.")
            return

        if not self.media_info:
            self.media_info = MediaInfo.get_info(filename, self.app_path)

        if self.media_info:
            builder = FFmpegCommandBuilder(settings, self.media_info)
            cmd = builder.build_command(filename)

            self.cmd_text.delete(1.0, tk.END)
            if isinstance(cmd, list):
                self.cmd_text.insert(tk.END, "\n".join(cmd))
            else:
                self.cmd_text.insert(tk.END, cmd)

    def on_process_button(self):
        """작업 실행/중지 버튼 이벤트"""
        if self.process_thread and self.process_thread.is_alive():
            self.stop_current_process()
        else:
            self.start_process()

    def start_process(self):
        """작업 시작"""
        if self.file_listbox.size() == 0:
            messagebox.showinfo("알림", "파일을 추가하세요.")
            return

        # FFmpeg 확인
        if not self.check_ffmpeg():
            messagebox.showerror(
                "오류",
                "FFmpeg.exe 파일이 없습니다.\nhttps://www.gyan.dev/ffmpeg/builds/ 에서 다운로드 하세요.",
            )
            return

        # 쓰레드로 실행
        self.stop_process = False
        self._set_process_button("작업 중지", "red")
        self.process_thread = threading.Thread(target=self.do_process, daemon=True)
        self.process_thread.start()

    def stop_current_process(self):
        """현재 진행 중인 작업 강제 중지"""
        self.stop_process = True
        self.status_label.config(text="중지 중...")

        with self.process_lock:
            process = self.current_process

        if process and process.poll() is None:
            process.kill()

    def _finish_process(self, status_text: str):
        """작업 종료 후 UI 상태 복원"""
        self._set_process_button("작업 실행", self.process_button_default_fg)
        self.status_label.config(text=status_text)

    def _set_process_button(self, text: str, fg: str):
        """작업 버튼 텍스트 변경 후 일정시간 동안 클릭 방지"""
        disable_tile = 1500
        self.process_button_state_token += 1
        token = self.process_button_state_token
        self.process_button.config(text=text, fg=fg, state=tk.DISABLED)
        self.root.after(disable_tile, lambda: self._enable_process_button(token))

    def _enable_process_button(self, token: int):
        """가장 최근 버튼 상태 변경에 대해서만 버튼 활성화"""
        if token == self.process_button_state_token:
            self.process_button.config(state=tk.NORMAL)

    def check_ffmpeg(self) -> bool:
        """FFmpeg 존재 여부 확인"""
        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            # 앱 경로에서 확인
            ffmpeg_path = os.path.join(self.app_path, "ffmpeg.exe")
            return os.path.exists(ffmpeg_path)

    # 외부창으로 실행
    def _run_cmd_ext(self, cmd):
        """새 콘솔 창에서 명령 실행 (따옴표 중첩 문제 방지)"""
        try:
            print(f"Running command: {cmd}")
            subprocess.Popen(f"cmd /c {cmd}", creationflags=subprocess.CREATE_NEW_CONSOLE)
        except Exception as e:
            print(f"Error: {e}")

    def _run_cmd(self, cmd, create_new_console=False):
        """콘솔 창에서 명령 실행"""
        try:
            print(f"Running command: {cmd}")
            if create_new_console:
                process = subprocess.Popen(f"cmd /c {cmd}", creationflags=subprocess.CREATE_NEW_CONSOLE)
            else:
                # cmd.exe를 거치면 한글 등 유니코드 인코딩이 깨지므로 직접 실행
                process = subprocess.Popen(cmd)

            with self.process_lock:
                self.current_process = process

            process.wait()

            with self.process_lock:
                if self.current_process == process:
                    self.current_process = None

            print(f"-------------------------------------\n명령 종료:\n {cmd}")

        except Exception as e:
            print(f"Error: {e}")
            with self.process_lock:
                self.current_process = None

    def do_process(self):
        """실제 처리 작업"""
        status_text = "완료"

        try:
            settings = self.get_settings()
            files = settings["files"]
            process_kind = settings["process_kind"]
            total_files = len(files)

            # 합치기 (영상 + 소리) - 단일 명령으로 처리
            if process_kind == PROC_KIND_MERGE_VA:
                media_info = MediaInfo.get_info(files[0], self.app_path) if files else None
                if media_info:
                    builder = FFmpegCommandBuilder(settings, media_info)
                    cmd = builder.build_command(files[0])
                    self._run_cmd(cmd)
                return

            for i, filename in enumerate(files):
                if self.stop_process:
                    break

                # 상태 업데이트
                self.root.after(
                    0,
                    lambda f=filename, current=i + 1, total=total_files: self.status_label.config(
                        text=f"처리 중 ({current}/{total}): {f}"
                    ),
                )

                # 미디어 정보
                media_info = MediaInfo.get_info(filename, self.app_path)
                if not media_info:
                    continue

                # 태그 삭제는 지정된 음악 파일만 처리
                if process_kind == PROC_KIND_DELETE_TAGS and not is_tag_delete_audio_file(filename):
                    continue

                # 오디오 추출 시 오디오 트랙이 없으면 건너뛰기
                if (
                    process_kind in (PROC_KIND_EXTRACT_AUDIO, PROC_KIND_DELETE_TAGS)
                    and media_info.audio_count == 0
                ):
                    continue

                # 자막 추출 시 자막 트랙이 없으면 건너뛰기
                if process_kind == PROC_KIND_EXTRACT_SUB and media_info.sub_count == 0:
                    continue

                # 명령어 생성
                builder = FFmpegCommandBuilder(settings, media_info)

                # 자막 추출은 트랙별 개별 명령어
                if process_kind == PROC_KIND_EXTRACT_SUB:
                    cmds = builder.build_command(filename)
                    for cmd in cmds:
                        if self.stop_process:
                            break
                        self._run_cmd(cmd)
                    continue

                # MERGE: 개별 .ts 변환에는 pause 없음 (마지막 concat 명령에서 pause)
                add_pause = False
                if process_kind == PROC_KIND_MERGE:
                    add_pause = False
                else:
                    # add_pause = i == len(files) - 1
                    pass

                cmd = builder.build_command(filename, add_pause)

                # 실행
                self._run_cmd(cmd)

            # 합치기 (동영상+동영상) - .ts 변환 후 최종 합치기
            if not self.stop_process and process_kind == PROC_KIND_MERGE and len(files) >= 2:
                name, ext = divide_name(files[0])
                output_file = f"{name}_ALL.{ext}"
                cmd = FFmpegCommandBuilder.build_merge_all_command(files, output_file)

                if cmd:
                    self._run_cmd(cmd)

        except Exception as e:
            status_text = "오류"
            print(f"Error: {e}")
        finally:
            if self.stop_process:
                status_text = "중지됨"
            self.root.after(0, lambda text=status_text: self._finish_process(text))


def main():
    # 드래그 앤 드롭 지원 여부에 따라 root 생성
    if HAS_DND:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()

    app = VidGadgetApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
