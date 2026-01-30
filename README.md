#Video Player

This is a simple desktop video player built with Python, PyQt5, and VLC.
It allows you to open a folder and play videos from that folder and all subfolders using a clean dark interface.

The app remembers playback progress, volume, speed, and other settings automatically.

Features

Open and scan a folder of videos
Play videos using VLC backend
Dark modern interface
Search videos by name or folder
Sort videos by name, folder, or size
Shuffle and loop playback
Resume videos from last position
Subtitle and audio track selection
Keyboard shortcuts for playback
Drag and drop a folder into the app

##Supported video formats

The player supports the following video and media formats:

.mp4 .mkv .avi .mov .webm .wmv .flv .mpeg .mpg .m4v .3gp .ogv .ts .m2ts .mts .vob .asf .mpe .mp2 .mpv .f4v .divx .xvid .ogm .rm .rmvb .qt .m1v .m2v .m3u8 .h264 .hevc .mxf .dv .drc .nsv .yuv .amv .avchd .gifv .m2p .m2t .mp4v .3g2 .m4p .m4b .m4r .m4a .ogx .mka .mks .mk3d

##Requirements

Python 3.8 or newer
VLC media player must be installed on your system

The application will not run without VLC installed.

##How to run

Clone the repository

git clone https://github.com/Raze404/Video-player.git

cd yourrepo

Install dependencies

pip install -r requirements.txt

##Install VLC(NON VLC VERSION IN WORKS SO A NEW VIDEO PLAYER THAT RUNS LOCALLY LIKE VLC BUT BETTER)

Windows
Download and install VLC from the official VLC website

Linux
Install VLC using your system package manager

macOS
Install VLC using the official installer or Homebrew

Run the application

python v.py

On startup, you will be asked to select a folder containing videos.
You can change the folder later using the Open button or by dragging a folder into the window.

Keyboard shortcuts

Space to play or pause
Left and Right arrows to seek
N for next video
P for previous video
F for fullscreen
M to mute
S to toggle shuffle
R to change loop mode

Configuration

Settings are saved automatically on your system.
This includes volume, playback speed, shuffle mode, loop mode, and resume position.
