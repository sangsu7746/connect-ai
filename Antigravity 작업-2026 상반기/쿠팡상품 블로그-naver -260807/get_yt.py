import subprocess
import json
from youtube_transcript_api import YouTubeTranscriptApi

urls = [
    "https://www.youtube.com/watch?v=2a5rW4bd9IE",
    "https://www.youtube.com/watch?v=h5rpmZ2j-4o",
    "https://www.youtube.com/watch?v=G20k-ZiosVY",
    "https://www.youtube.com/watch?v=ulamOJ0pIcw"
]

def get_video_info():
    for url in urls:
        print(f"\n[{url}]")
        video_id = url.split("v=")[1]
        try:
            # Get Title using yt-dlp
            res = subprocess.run(["yt-dlp", "--dump-json", url], capture_output=True, text=True)
            if res.returncode == 0:
                info = json.loads(res.stdout)
                print(f"Title: {info.get('title')}")
            else:
                print("Failed to get title")
                
            # Get Transcript
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['ko', 'en'])
            text = " ".join([t['text'] for t in transcript_list])
            print(f"Transcript (first 500 chars): {text[:500]}...")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == '__main__':
    get_video_info()
