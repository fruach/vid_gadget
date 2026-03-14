# VidGadget

![VidGadget](vidgadget-200.png)

FFmpeg 기반 비디오/오디오 변환 GUI 도구 (Python/Tkinter)

## 주요 기능

- **비디오 변환**: H.264, H.265(HEVC), AV1, GIF, WEBP 등
- **오디오 변환**: MP3, AAC, OGG, OPUS, WAV, FLAC 등
- **추출**: 동영상에서 영상만 또는 소리만 추출
- **합치기**: 여러 동영상 합치기, 영상+소리 합치기
- **구간 편집**: 특정 구간만 추출
- **GPU 가속**: NVIDIA NVENC 지원
- **해상도 변경**: 720p, 1080p 등

## 요구사항

- Python 3.8+
- FFmpeg (PATH에 등록 또는 같은 폴더에 위치)
- MediaInfo (선택사항)

## 설치

### scoop 로 ffmpeg 설치

- 윈도우 패키지 관리자 scoop 설치

powershell 실행
```powershell
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
Invoke-RestMethod -Uri 'https://get.scoop.sh' | Invoke-Expression
```

cmd.exe 에서 한줄 명령:
```cmd
powershell -Command "Set-ExecutionPolicy RemoteSigned -Scope CurrentUser; Invoke-RestMethod -Uri 'https://get.scoop.sh' | Invoke-Expression"
```

- python 설치
```bash
scoop install git
scoop bucket add versions
scoop install python312
scoop update python312
```

- ffmpeg 설치
```bash
scoop install ffmpeg
scoop update ffmpeg
```

### Python 패키지 설치

```bash
pip install -r requirements.txt
```

## 실행
```
vidGadget.bat
```

## 사용법

1. "파일 추가" 또는 드래그 앤 드롭으로 파일 선택
2. 코덱, 품질, 해상도 등 옵션 설정
3. 작업 종류 선택 (변환, 추출, 합치기)
4. "작업 실행" 클릭

