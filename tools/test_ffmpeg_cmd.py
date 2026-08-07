import os
import re
import tempfile
import unittest

from ffmpeg_cmd import FFmpegCommandBuilder, PROC_KIND_EXTRACT_AUDIO
from media_info import AudioInfo, CODEC_265, CODEC_AVC, LANG_ENGLISH, MEDIA_INFO


class CropCommandTest(unittest.TestCase):
    def test_explicit_crop_start_position_is_preserved(self):
        media_info = MEDIA_INFO(codec=CODEC_AVC, width=1920, height=1080)
        settings = {
            "output_codec": CODEC_265,
            "crop": True,
            "crop_w": 9,
            "crop_h": 16,
            "crop_x": 100,
            "crop_y": 200,
        }

        builder = FFmpegCommandBuilder(settings, media_info)

        self.assertEqual((494, 880, 100, 200), builder._get_crop_rect())
        self.assertIn(
            '-vf "crop=w=494:h=880:x=100:y=200:exact=1"',
            builder.build_command("input.mp4"),
        )


class ExtractAudioCommandTest(unittest.TestCase):
    def test_uses_short_track_metadata_in_output_filename(self):
        input_file = (
            r"D:\_Down\Torrent\Completed\Ready or Not 2꞉ Here I Come (2026)"
            r"\Ready or Not 2꞉ Here I Come (2026) (1080p BluRay x265 Ghost).mkv"
        )
        media_info = MEDIA_INFO(
            audio_count=3,
            audio_tracks=[
                AudioInfo(
                    title="Surround 5.1",
                    codec_id="eac3",
                    bitrate=768,
                    channel=6,
                    lang=LANG_ENGLISH,
                ),
                AudioInfo(
                    title=(
                        "Commentary w/directors Matt Bettinelli-Olpin & Tyler Gillett "
                        "& actors Samara Weaving & Kathryn Newton"
                    ),
                    codec_id="ac3",
                    bitrate=192,
                    channel=2,
                    lang=LANG_ENGLISH,
                ),
                AudioInfo(
                    title=(
                        "Commentary w/directors Matt Bettinelli-Olpin & Tyler Gillett, "
                        "writers Guy Busick & R. Christopher Murphy, producers James "
                        "Vanderbilt & Tripp Vinson & editor Jay Prychidny"
                    ),
                    codec_id="ac3",
                    bitrate=192,
                    channel=2,
                    lang=LANG_ENGLISH,
                ),
            ],
        )
        builder = FFmpegCommandBuilder(
            {"process_kind": PROC_KIND_EXTRACT_AUDIO}, media_info
        )

        command = builder.build_command(input_file)
        output_files = re.findall(r'"([^"]+)"', command)[1:]

        self.assertEqual(3, len(output_files))
        self.assertTrue(all(len(path) <= 259 for path in output_files))
        self.assertTrue(all(len(os.path.basename(path)) <= 255 for path in output_files))
        self.assertIn(".a1.Surround.768k.6ch.en.eac3", output_files[0])
        self.assertIn(".a2.Commenta.192k.2ch.en.ac3", output_files[1])
        self.assertIn(".a3.Commenta.192k.2ch.en.ac3", output_files[2])
        self.assertTrue(output_files[2].endswith(".192k.2ch.en.ac3"))

    def test_duplicate_output_filename_gets_numbered_suffix(self):
        with tempfile.TemporaryDirectory() as output_dir:
            input_file = os.path.join(output_dir, "ready.mkv")
            existing_file = os.path.join(
                output_dir, "ready.a1.Commenta.192k.2ch.ac3"
            )
            with open(existing_file, "wb"):
                pass

            media_info = MEDIA_INFO(
                audio_count=1,
                audio_tracks=[
                    AudioInfo(
                        title="Commentary",
                        codec_id="ac3",
                        bitrate=192,
                        channel=2,
                    )
                ],
            )
            builder = FFmpegCommandBuilder(
                {"process_kind": PROC_KIND_EXTRACT_AUDIO}, media_info
            )

            builder.build_command(input_file)
            _, final_output = builder.extract_audio_outputs[0]

            self.assertEqual(
                os.path.join(output_dir, "ready.a1.Commenta.192k.2ch_(02).ac3"),
                final_output,
            )

    def test_extracts_to_temp_and_keeps_final_output_paths(self):
        input_file = r"D:\media\movie.mkv"
        media_info = MEDIA_INFO(
            audio_count=1,
            audio_tracks=[
                AudioInfo(
                    title="Very long track title " * 20,
                    codec_id="ac3",
                    bitrate=192,
                    channel=2,
                )
            ],
        )
        temp_dir = os.path.join(tempfile.gettempdir(), "vidgadget_audio_test")
        builder = FFmpegCommandBuilder(
            {
                "process_kind": PROC_KIND_EXTRACT_AUDIO,
                "extract_audio_temp_dir": temp_dir,
            },
            media_info,
        )

        command = builder.build_command(input_file)
        temp_output, final_output = builder.extract_audio_outputs[0]

        self.assertIn(f'"{temp_output}"', command)
        self.assertEqual(temp_dir, os.path.dirname(temp_output))
        self.assertEqual(r"D:\media", os.path.dirname(final_output))
        self.assertEqual(os.path.basename(final_output), os.path.basename(temp_output))
        self.assertLessEqual(len(temp_output), 254)


if __name__ == "__main__":
    unittest.main()
