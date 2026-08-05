import unittest

from ffmpeg_cmd import FFmpegCommandBuilder
from media_info import CODEC_265, CODEC_AVC, MEDIA_INFO


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


if __name__ == "__main__":
    unittest.main()
