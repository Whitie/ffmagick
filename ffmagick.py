#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Simple slideshow maker. The following external tools are needed:
    - ffmpeg
    - imagemagick (convert, mogrify, montage)
    - mkvtoolnix (mkvmerge)
"""

import multiprocessing as mp
import os
import shutil
import subprocess
import sys
import time

from argparse import ArgumentParser
from datetime import date
from imghdr import what
from itertools import cycle, tee
from random import randint
from tempfile import gettempdir
from threading import Thread
from xml.sax.saxutils import escape


__version__ = '0.1'

DEFAULT_FONT = 'Cooper-Black' if os.name == 'nt' else 'DejaVu-Sans-Book'
_P = cycle('\\|/-')
_win = 'r' if os.name == 'nt' else ''
_exe = '.exe' if os.name == 'nt' else ''
EXT = ('tiff', 'jpeg', 'bmp', 'png')
AUDIO_EXT = ('.wav', '.ogg', '.mp3', '.m4a', '.aac')
EXECUTABLES = {
    'ffmpeg': 'ffmpeg',
    'convert': 'convert',
    'mogrify': 'mogrify',
    'montage': 'montage',
    'mkvmerge': 'mkvmerge',
}
TAGFILE_CONTENT = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE Tags SYSTEM "matroskatags.dtd">

<Tags>
    <Tag>
        <Simple>
            <Name>DESCRIPTION</Name>
            <String>{epilog}</String>
        </Simple>
        <Simple>
            <Name>DATE_RELEASED</Name>
            <String>{date}</String>
        </Simple>
        <Simple>
            <Name>COMMENT</Name>
            <String>Created with ffmagick slideshow maker.</String>
        </Simple>
        <Simple>
            <Name>COPYRIGHT</Name>
            <String>{author}</String>
        </Simple>
    </Tag>
</Tags>
"""
BUILDFILE_CONTENT = """\
# -*- coding: utf-8 -*-

from ffmagick import slideshow, recurse, recurse_audio


# Put your images and/or image directories here. If you have subfolders,
# which should be included, use the `recurse` function provided.
# Example: IMAGES = [
#               '/home/user/mypic.jpg',
#               recurse('/home/user/fotos'),
#               '/home/user/myfolder',
#          ]
# On Windows use raw strings like r'C:\\Users\\user\\pictures'
IMAGES = []

# Put your audio files and/or directories here. If you have subfolders,
# which should be included, use the `recurse_audio` function provided.
# Example: AUDIO = [
#               '/home/user/song.mp3',
#               recurse_audio('/home/user/music'),
#               '/home/user/audiofolder'
#          ]
# On Windows use raw strings like r'C:\\Users\\user\\music'
AUDIO = []

# Output profile for your show.
# Available profiles: DVD (720x576, 30Hz)
#                     720p (1280x720, 60Hz)
#                     1080p (1920x1080, 60Hz)
#                     UHD (3840x2160, 60Hz)
#                     4k (4096x2304, 60Hz)
PROFILE = '1080p'

# Time to display each image in seconds.
IMAGE_DURATION = 5

# Time for the transition between two images in seconds.
TRANSITION_DURATION = 1

# Set your font here. Run `python ffmagick.py list_fonts` for a list of
# supported fonts of your platform. The best way is to give an absolute
# path to a .ttf file here. System fonts can be used without path.
# On Windows use raw strings like r'C:\\windows\\fonts\\coopbl.ttf'
FONT = '{font}'

# Title for your slideshow
TITLE = ''

# Author of the slideshow
AUTHOR = ''

# Text shown at the end of the show. Use `\\n` as newline even on Windows.
EPILOG = ''

# Background color for text and around the images after resizing.
BACKGROUND = 'black'

# Color for title and epilog text.
TEXTCOLOR = 'white'

# Working directory for temporary files (for a show with 4 pictures about
# 120MB free space is needed)
# If None (the default) your systems temporary directory is used.
WORKDIR = None

# Mapping for the needed external programs if not in your PATH.
# On Windows use raw strings like r'C:\\Progam Files\\ImageMagick\\convert.exe'
EXECUTABLES = {{
    'convert': {win}'convert{exe}',
    'montage': {win}'montage{exe}',
    'mogrify': {win}'mogrify{exe}',
    'ffmpeg': {win}'ffmpeg{exe}',
    'mkvmerge': {win}'mkvmerge{exe}',
}}

# Remove all temporary files after slideshow is finished.
# If set to True, the needed HD space is much less. Images then will be
# removed right after small movie creation.
REMOVE_TEMPFILES = True

# Filename for your created slideshow.
OUTPUT = {win}'{out}'


if __name__ == '__main__':
    slideshow(
        IMAGES,
        AUDIO,
        remove_tempfiles=REMOVE_TEMPFILES,
        output=OUTPUT,
        profile=PROFILE,
        image_duration=IMAGE_DURATION,
        transition_duration=TRANSITION_DURATION,
        font=FONT,
        title=TITLE,
        author=AUTHOR,
        epilog=EPILOG,
        background=BACKGROUND,
        textcolor=TEXTCOLOR,
        workdir=WORKDIR,
        executables=EXECUTABLES,
    )
""".format(font=DEFAULT_FONT, win=_win, exe=_exe,
           out=os.path.join(os.getcwd(), 'slideshow.mkv'))


class Profile:

    def __init__(self, width, height, fps, fontsize=None):
        self.width = width
        self.height = height
        self.fps = fps
        self.fontsize = fontsize

    @property
    def size(self):
        return (self.width, self.height)

    @property
    def montage_width(self):
        return self.width // 2

    @property
    def montage_height(self):
        return self.height // 2

    @property
    def montage_size(self):
        return (self.montage_width, self.montage_height)


PROFILES = {
    'dvd': Profile(720, 576, 30, 48),
    '720p': Profile(1280, 720, 60, 80),
    '1080p': Profile(1920, 1080, 60, 80),
    'uhd': Profile(3840, 2160, 60, 80),
    '4k': Profile(4096, 2304, 60, 80),
}


class Base:

    def __init__(self, workdir, executables, outfile=None):
        workdir = workdir or gettempdir()
        _name = 'ffmagick-{}-'.format(self.__class__.__name__)
        self.tmp = _get_name(workdir, _name)
        os.mkdir(self.tmp)
        self.exe = EXECUTABLES.copy()
        if executables:
            self.exe.update(executables)
        self.outfile = outfile
        self.process_time = None
        self._automate = []

    def __iter__(self):
        start = time.time()
        for desc, func in self._automate:
            _start = time.time()
            func()
            yield desc, time.time() - _start
        self.process_time = time.time() - start

    def cleanup(self):
        shutil.rmtree(self.tmp)


class VideoBuilder(Base):

    def __init__(self, pictures, profile=PROFILES['1080p'],
                 title='', background='black', textcolor='white',
                 font=DEFAULT_FONT, workdir=None, author='', epilog='',
                 executables=None, image_duration=5, transition_duration=1,
                 remove_tempfiles=True):
        Base.__init__(self, workdir, executables)
        self.source_pictures = _get_pictures(pictures)
        self.pictures = []
        self.first = None
        self.last = None
        self._last_num = None
        self.anim_nums = []
        self.profile = profile
        self.title = title
        self.background = background
        self.textcolor = textcolor
        self.font = font
        self.author = author
        self.epilog = epilog
        self.image_duration = image_duration
        self.transition_duration = transition_duration
        self.remove_tempfiles = remove_tempfiles
        self.dirs = dict(
            pics=os.path.join(self.tmp, 'pictures'),
            anim_pics=os.path.join(self.tmp, 'animation_pictures'),
            movs=os.path.join(self.tmp, 'movies'),
        )
        for d in self.dirs.values():
            os.mkdir(d)
        self._automate = (
            ('Copied source files to workdir', self.copy_source_files),
            ('Created first picture with fade-in', self.create_first_picture),
            ('Created last picture with fade-out', self.create_last_picture),
            ('Resized pictures according to profile', self.resize_pictures),
            ('Created animation pictures', self.create_anim_pictures),
            # ('Created movies for pictures', self.create_small_movies),
            # ('Created movies for transitions',
            # self.create_transition_movies),
            ('Created small movies', self.create_movies),
            ('Created video only MKV file', self.create_video_only_mkv),
        )

    def copy_source_files(self):
        i = 3
        for pic in self.source_pictures:
            dest = os.path.join(self.dirs['pics'], 'pic-{:>06d}.jpg'.format(i))
            cmd = [self.exe['convert'], pic, '-auto-orient', dest]
            subprocess.check_call(cmd)
            self.pictures.append(dest)
            i += 2
        self._last_num = i

    def create_first_picture(self):
        if len(self.pictures) < 4:
            raise ValueError('You must at least have 4 pictures in your show!')
        nums = _get_sample_numbers(len(self.pictures))
        pics = [self.pictures[x] for x in nums]
        _out = os.path.join(self.dirs['pics'], 'pic-000001.jpg')
        if self.title:
            out = os.path.join(self.tmp, 'title_raw.jpg')
        else:
            out = _out
        cmd = [self.exe['montage'], '-tile', '2x']
        cmd.extend(pics)
        cmd.extend([
            '-geometry',
            '{}x{}+10+50'.format(
                self.profile.montage_width, self.profile.montage_height
            ),
            '-background',
            self.background,
            out
        ])
        subprocess.check_call(cmd)
        if self.title:
            cmd = [self.exe['convert'], out, '-gravity', 'center', '-font',
                   self.font, '-pointsize', str(self.profile.fontsize),
                   '-fill', self.textcolor,
                   '-draw', "text 0,0 '{}'".format(self.title), _out]
            subprocess.check_call(cmd)
        self.first = _out

    def create_last_picture(self):
        w, h = self.profile.size
        text = []
        now = date.today()
        if not self.author and not self.epilog:
            text.append('Build with ffmagick {}'.format(now.year))
        else:
            if self.author:
                text.append('\xa9 {} {}'.format(now.year, self.author))
            if self.epilog:
                text.append(self.epilog)
        out = os.path.join(self.dirs['pics'],
                           'pic-{:>06d}.jpg'.format(self._last_num))
        cmd = [self.exe['convert'], '-size', '{}x{}'.format(w, h),
               '-background', self.background, '-fill', self.textcolor,
               '-font', self.font, '-pointsize', str(self.profile.fontsize),
               '-gravity', 'center', 'label:{}'.format('\n'.join(text)), out]
        subprocess.check_call(cmd)
        self.last = out

    def resize_pictures(self):
        # start = time.time()
        size = '{}x{}'.format(*self.profile.size)
        pics = [self.first] + self.pictures + [self.last]
        for pic in pics:
            cmd = [self.exe['mogrify'], '-resize', size, '-background',
                   'black', '-gravity', 'center', '-extent', size, pic]
            subprocess.check_call(cmd)

    def create_anim_pictures(self):
        pics = [self.first] + self.pictures + [self.last]
        i = 2
        frames = self.profile.fps * self.transition_duration - 2
        for pic1, pic2 in _pairwise(pics):
            d = os.path.join(self.dirs['anim_pics'], 'morph-{:>06d}'.format(i))
            full = os.path.join(d, '%03d.jpg')
            os.mkdir(d)
            cmd = [self.exe['convert'], pic1, pic2, '-morph', str(frames),
                   full]
            self.anim_nums.append(i)
            subprocess.check_call(cmd)
            i += 2

    def create_small_movies(self):
        self._create_first_movie()
        # length = len(self.pictures)
        for pic in self.pictures:
            _name = os.path.basename(pic)
            name, _ = os.path.splitext(_name)
            out = os.path.join(self.dirs['movs'], 'mov-{}.mp4'.format(name))
            cmd = [self.exe['ffmpeg'], '-loop', '1', '-i', pic, '-c:v',
                   'libx264', '-t', str(self.image_duration), '-r',
                   str(self.profile.fps), '-pix_fmt', 'yuv420p', out]
            subprocess.check_call(cmd, stderr=subprocess.DEVNULL)
            if self.remove_tempfiles:
                os.remove(pic)
        self._create_last_movie()

    def create_transition_movies(self):
        anims = os.listdir(self.dirs['anim_pics'])
        anims.sort()
        for folder in anims:
            num = folder.split('-')[1]
            inp = os.path.join(self.dirs['anim_pics'], folder, '%03d.jpg')
            out = os.path.join(self.dirs['movs'], 'mov-pic-{}.mp4'.format(num))
            cmd = [self.exe['ffmpeg'], '-r', str(self.profile.fps), '-i',
                   inp, '-c:v', 'libx264', '-vf',
                   'fps={},format=yuv420p'.format(self.profile.fps), out]
            subprocess.check_call(cmd, stderr=subprocess.DEVNULL)
            if self.remove_tempfiles:
                shutil.rmtree(os.path.join(self.dirs['anim_pics'], folder))

    def create_movies(self):
        p = Thread(target=self.create_small_movies)
        p.start()
        self.create_transition_movies()
        p.join()

    def create_video_only_mkv(self):
        opts = os.path.join(self.tmp, 'video_only.txt')
        out = os.path.join(self.tmp, 'video_only.mkv')
        files = [os.path.join(self.dirs['movs'], x) for x in
                 os.listdir(self.dirs['movs'])]
        files.sort()
        tags_file = self._create_tags_file()
        with open(opts, 'w', encoding='utf-8') as fp:
            fp.write('-o\n{}\n'.format(out.replace('\\', '/')))
            if self.title:
                fp.write('--title\n')
                fp.write('{}\n'.format(self.title))
            fp.write('--global-tags\n')
            fp.write('{}\n\n'.format(tags_file.replace('\\', '/')))
            fp.write('{}\n'.format(files[0].replace('\\', '/')))
            for f in files[1:]:
                fp.write('+{}\n'.format(f.replace('\\', '/')))
        cmd = [self.exe['mkvmerge'], '@{}'.format(opts)]
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
        self.outfile = out

    def _create_tags_file(self):
        out = os.path.join(self.tmp, 'tags.xml')
        dt = date.today()
        text = TAGFILE_CONTENT.format(
            epilog=escape(self.epilog), author=escape(self.author),
            date=dt.strftime('%Y-%m-%d')
        )
        with open(out, 'w', encoding='utf-8') as fp:
            fp.write(text)
        return out

    def _create_first_movie(self):
        duration = self.image_duration + 2
        tmp_out = os.path.join(self.tmp, 'first.mp4')
        cmd = [self.exe['ffmpeg'], '-loop', '1', '-i', self.first,
               '-c:v', 'libx264', '-t', str(duration), '-r',
               str(self.profile.fps), '-y', '-pix_fmt', 'yuv420p', tmp_out]
        subprocess.check_call(cmd, stderr=subprocess.DEVNULL)
        out = os.path.join(self.dirs['movs'], 'mov-pic-000001.mp4')
        cmd = [self.exe['ffmpeg'], '-i', tmp_out, '-y', '-vf',
               'fade=in:0:{}'.format(self.profile.fps * 2), out]
        subprocess.check_call(cmd, stderr=subprocess.DEVNULL)

    def _create_last_movie(self):
        duration = self.image_duration + 2
        begin = duration * self.profile.fps - 2 * self.profile.fps
        tmp_out = os.path.join(self.tmp, 'last.mp4')
        cmd = [self.exe['ffmpeg'], '-loop', '1', '-i', self.last,
               '-c:v', 'libx264', '-t', str(duration), '-r',
               str(self.profile.fps), '-y', '-pix_fmt', 'yuv420p', tmp_out]
        subprocess.check_call(cmd, stderr=subprocess.DEVNULL)
        _name = os.path.basename(self.last)
        name, _ = os.path.splitext(_name)
        out = os.path.join(self.dirs['movs'], 'mov-{}.mp4'.format(name))
        cmd = [self.exe['ffmpeg'], '-i', tmp_out, '-y', '-vf',
               'fade=out:{}:{}'.format(begin, self.profile.fps * 2), out]
        subprocess.check_call(cmd, stderr=subprocess.DEVNULL)


class AudioBuilder(Base):

    def __init__(self, audio_files, workdir=None, executables=None):
        Base.__init__(self, workdir, executables)
        self.audio_files = _get_audio(audio_files)
        self.aac_files = []
        self._automate = (
            ('Transcoded audio files to AAC', self.transcode),
            ('Created audio only MKV file', self.create_audio_only_mkv),
        )

    def transcode(self):
        for n, f in enumerate(self.audio_files, 1):
            out = os.path.join(self.tmp, 'audio-{:>03d}.aac'.format(n))
            if f.lower().endswith('.aac') or f.lower().endswith('.m4a'):
                shutil.copy(f, out)
            else:
                cmd = [self.exe['ffmpeg'], '-i', f, '-c:a', 'aac', '-strict',
                       '-2', '-b:a', '256k', out]
                subprocess.check_call(cmd, stderr=subprocess.DEVNULL)
            self.aac_files.append(out)
        self.aac_files.sort()

    def create_audio_only_mkv(self):
        self.outfile = os.path.join(self.tmp, 'audio_only.mkv')
        opts = os.path.join(self.tmp, 'audio_only.txt')
        sbr = '--aac-is-sbr\n1\n'
        with open(opts, 'w', encoding='utf-8') as fp:
            fp.write('-o\n{}\n'.format(self.outfile.replace('\\', '/')))
            fp.write(sbr)
            fp.write('{}\n'.format(self.aac_files[0].replace('\\', '/')))
            for f in self.aac_files[1:]:
                fp.write(sbr)
                fp.write('+{}\n'.format(f.replace('\\', '/')))
        cmd = [self.exe['mkvmerge'], '@{}'.format(opts)]
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)


class Muxer(Base):

    def __init__(self, video_file, audio_file, outfile, workdir=None,
                 executables=None):
        Base.__init__(self, workdir, executables, outfile)
        self.video_file = video_file
        self.audio_file = audio_file
        self._counter = 1

    def mux(self):
        if not os.path.isfile(self.audio_file):
            shutil.copy(self.video_file, self.outfile)
            return
        vid_dur = _get_duration(self.video_file, self.exe['ffmpeg'])
        aud_dur = _get_duration(self.audio_file, self.exe['ffmpeg'])
        while True:
            if aud_dur < vid_dur:
                self._double_audio()
                aud_dur = _get_duration(self.audio_file, self.exe['ffmpeg'])
            else:
                break
        out = os.path.join(self.tmp, 'audio-cut-%02d.mkv')
        cmd = [self.exe['mkvmerge'], '-o', out, '--split',
               'timecodes:{}'.format(get_timecode(vid_dur)), self.audio_file]
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
        self.audio_file = os.path.join(self.tmp, 'audio-cut-01.mkv')
        cmd = [self.exe['mkvmerge'], '-o', self.outfile, self.video_file,
               self.audio_file]
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)

    def _double_audio(self):
        out = os.path.join(self.tmp, 'audio-{:>02d}.mkv'.format(self._counter))
        self._counter += 1
        cmd = [self.exe['mkvmerge'], '-o', out, self.audio_file, '+',
               self.audio_file]
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
        self.audio_file = out


def _worker(builder, queue):
    for desc, t in builder:
        print(desc, '| Duration: {:.1f}s'.format(t))
    queue.put(builder.outfile)


def slideshow(pictures, audio_files=None, remove_tempfiles=True,
              output='slideshow.mkv', **kwargs):
    if 'profile' in kwargs and not isinstance(kwargs['profile'], Profile):
        kwargs['profile'] = PROFILES[kwargs['profile'].lower()]
    if not output.lower().endswith('.mkv'):
        output = '{}.mkv'.format(output)
    kwargs['remove_tempfiles'] = remove_tempfiles
    workdir = kwargs.get('workdir', None)
    executables = kwargs.get('executables', None)
    start = time.time()
    vbuilder = VideoBuilder(pictures, **kwargs)
    vqueue = mp.Queue(1)
    vprocess = mp.Process(target=_worker, args=(vbuilder, vqueue))
    vprocess.start()
    if audio_files:
        abuilder = AudioBuilder(audio_files, workdir, executables)
        aqueue = mp.Queue(1)
        aprocess = mp.Process(target=_worker, args=(abuilder, aqueue))
        aprocess.start()
    while True:
        if not vprocess.is_alive():
            if audio_files and not aprocess.is_alive():
                break
        print(next(_P), end='\r', file=sys.stderr, flush=True)
        time.sleep(0.2)
    video = vqueue.get()
    if audio_files:
        audio = aqueue.get()
        muxer = Muxer(video, audio, output, workdir, executables)
        muxer.mux()
    else:
        shutil.copy(video, output)
    if remove_tempfiles:
        print('Removing temporary files')
        vbuilder.cleanup()
        if audio_files:
            abuilder.cleanup()
            muxer.cleanup()
    duration = time.time() - start
    print('Duration of the whole process: {}'.format(
        get_timecode(duration, only_int=True)
    ))
    return output


def recurse(folder):
    folder = os.path.abspath(folder)
    for root, _, files in os.walk(folder):
        for f in files:
            full = os.path.join(root, f)
            if what(full) in EXT:
                yield full


def recurse_audio(folder):
    folder = os.path.abspath(folder)
    for root, _, files in os.walk(folder):
        for f in files:
            full = os.path.join(root, f)
            if os.path.splitext(f)[1].lower() in AUDIO_EXT:
                yield full


def get_timecode(seconds, only_int=False):
    """Convert a number of seconds in a timecode (HH:MM:SS.ssss) which
       MKVMerge can handle.

    :parameters:
        seconds : Decimal
            The seconds to convert.
        only_int : bool
            If given, the returntype will be HH:MM:SS

    :returns: Timecode in the format HH:MM:SS.ssss
    :rtype: str
    """
    minute, second = divmod(int(seconds), 60)
    hour, minute = divmod(minute, 60)
    second = seconds - minute * 60 - hour * 3600
    if only_int:
        format_str = '{:0>2d}:{:0>2d}:{:0>2.0f}'
    else:
        format_str = '{:0>2d}:{:0>2d}:{:0>7.4f}'
    return format_str.format(hour, minute, second)


def _progress(num, count=None):
    pass


def _get_seconds(s):
    h, m, s = s.split(':')
    return int(h) * 3600 + int(m) * 60 + float(s)


def _get_duration(filename, ffmpeg):
    cmd = [ffmpeg, '-i', filename]
    p = subprocess.Popen(cmd, stderr=subprocess.PIPE)
    dur = None
    for line in p.stderr:
        line = line.decode('utf-8').strip()
        if 'Duration' in line:
            tmp = line.split(',')[0]
            dur = tmp.split()[1]
    if dur is None:
        raise ValueError('No duration found for {}'.format(filename))
    return _get_seconds(dur)


def _get_name(dir_, prefix):
    root = os.path.abspath(dir_)
    num = 1
    while True:
        name = os.path.join(root, '{}{:>03d}'.format(prefix, num))
        if not os.path.exists(name):
            return name
        num += 1


def _pairwise(pictures):
    a, b = tee(pictures)
    next(b, None)
    return zip(a, b)


def _get_sample_numbers(max_num):
    nums = set()
    while True:
        num = randint(0, max_num - 1)
        nums.add(num)
        if len(nums) == 4:
            return nums


def _get_pictures(files_and_folders):
    files = []
    for item in files_and_folders:
        if not isinstance(item, str):
            files.extend(list(item))
        elif os.path.isfile(item):
            pic = os.path.abspath(item)
            if what(pic) in EXT:
                files.append(pic)
        elif os.path.isdir(item):
            root = os.path.abspath(item)
            for f in os.listdir(root):
                full = os.path.join(root, f)
                if what(full) in EXT:
                    files.append(full)
    return files


def _get_audio(files_and_folders):
    files = []
    for item in files_and_folders:
        if not isinstance(item, str):
            files.extend(list(item))
        elif os.path.isfile(item):
            f = os.path.abspath(item)
            ext = os.path.splitext(f)[1].lower()
            if ext in AUDIO_EXT:
                files.append(f)
        elif os.path.isdir(item):
            root = os.path.abspath(item)
            for f in os.listdir(root):
                full = os.path.join(root, f)
                ext = os.path.splitext(f)[1].lower()
                if ext in AUDIO_EXT:
                    files.append(full)
    return files


def paste_buildfile(args):
    with open(args.output, 'w', encoding='utf-8') as fp:
        fp.write(BUILDFILE_CONTENT)


def print_fonts(args):
    p = subprocess.Popen(
        [args.convert, '-list', 'font'], stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL
    )
    fonts = []
    default_font_found = False
    for line in p.stdout:
        line = line.decode('utf-8').strip()
        if 'Font:' in line:
            font = line.split()[1].strip()
            fonts.append(font)
            if font == DEFAULT_FONT:
                default_font_found = True
    p.wait()
    print('')
    count = len(fonts) + 1
    for f in fonts:
        print(' *', f)
    found = '(not found on your system)' if not default_font_found else ''
    print(' ** Default font:', DEFAULT_FONT, found)
    print('')
    print('Found {} fonts.'.format(count))
    print('')


def find_progs(args):
    print('')
    print('Looking for ImageMagick')
    for prog in ('convert', 'montage', 'mogrify'):
        p = shutil.which(prog)
        print(' * {}: {}'.format(prog, p or 'not found'))
    print('')
    print('Looking for ffmpeg')
    p = shutil.which('ffmpeg')
    print(' * ffmpeg: {}'.format(p or 'not found'))
    print('')
    print('Looking for mkvtoolnix')
    p = shutil.which('mkvmerge')
    print(' * mkvmerge: {}'.format(p or 'not found'))
    print('')
    print('If one or more components are not found, install them or give '
          'the full path to the executables in your buildfile or on the '
          'commandline.')
    print('')


def _get_file(filename):
    with open(filename, encoding='utf-8') as fp:
        return fp.read()


def _get_audio_from_file(filename):
    tracks = []
    with open(filename, encoding='utf-8') as fp:
        for f in fp:
            f = f.strip()
            if not f:
                continue
            if f.startswith('+'):
                tracks.append(recurse_audio(f[1:].strip()))
            else:
                tracks.append(f)
    return tracks


def _get_images_from_file(filename):
    images = []
    with open(filename, encoding='utf-8') as fp:
        for f in fp:
            f = f.strip()
            if not f:
                continue
            if f.startswith('+'):
                images.append(recurse(f[1:].strip()))
            else:
                images.append(f)
    return images


def _slideshow(args):
    args = vars(args)
    _audio = args.pop('audio_files')
    audio_files = []
    for f in _audio:
        if f.startswith('+'):
            audio_files.append(recurse_audio(f[1:]))
        elif f.startswith('@'):
            audio_files.extent(_get_audio_from_file(f[1:]))
        else:
            audio_files.append(f)
    _img = args.pop('images')
    images = []
    for f in _img:
        if f.startswith('+'):
            images.append(recurse(f[1:]))
        elif f.startswith('@'):
            images.extent(_get_images_from_file(f[1:]))
        else:
            images.append(f)
    for k in ('title', 'epilog'):
        if args[k].startswith('@'):
            args[k] = _get_file(args[k][1:])
    args['executables'] = {
        'convert': args.pop('convert'),
        'montage': args.pop('montage'),
        'mogrify': args.pop('mogrify'),
        'ffmpeg': args.pop('ffmpeg'),
        'mkvmerge': args.pop('mkvmerge'),
    }
    del args['version']
    del args['func']
    print(args)
    # return slideshow(images, audio_files, **args)


def main():
    _convert = 'convert.exe' if os.name == 'nt' else 'convert'
    _montage = 'montage.exe' if os.name == 'nt' else 'montage'
    _mogrify = 'mogrify.exe' if os.name == 'nt' else 'mogrify'
    _ffmpeg = 'ffmpeg.exe' if os.name == 'nt' else 'ffmpeg'
    _mkv = 'mkvmerge.exe' if os.name == 'nt' else 'mkvmerge'
    p = ArgumentParser(
        description='Create slideshows with transitions, title slide and '
        'music from any number of images as MKV file.', prog='ffmagick',
        epilog='Needed external software: ImageMagick, ffmpeg, mkvmerge'
    )
    p.add_argument('--version', action='store_true', default=False,
                   help='Print version info and exit')
    subparsers = p.add_subparsers(title='Actions')
    p_fonts = subparsers.add_parser(
        'list_fonts', help='List fonts known by your convert program',
        aliases=['lf']
    )
    p_fonts.add_argument('--convert', default=_convert, help='Path to '
                         'convert(.exe) binary (default: %(default)s)')
    p_fonts.set_defaults(func=print_fonts)
    p_progs = subparsers.add_parser(
        'list_progs', help='Try to find the needed external programs and '
        'list them', aliases=['lp']
    )
    p_progs.set_defaults(func=find_progs)
    p_build = subparsers.add_parser(
        'buildfile', help='Create a default buildfile in the current working '
        'directory or at a location given with the -o option', aliases=['bf']
    )
    p_build.add_argument('-o', '--output', default='ffmagick_build.py',
                         help='Name of the buildfile (default: %(default)s)')
    p_build.set_defaults(func=paste_buildfile)
    p_slide = subparsers.add_parser(
        'slideshow', help='Build a slideshow with the given parameters',
        epilog='You can prefix the values for title and epilog with an @ '
        'to indicate that the value is a file.', aliases=['sl']
    )
    p_slide.add_argument('images', nargs='+', help='Give all your images/'
                         'image folders here. Prefix folders with a + to '
                         'indicate that they should be searched recursive. '
                         'If prefixed with an @ values are read from file '
                         '(one per line)')
    p_slide.add_argument('-a', '--audio-files', nargs='+', default=[],
                         help='Give all your audio files/folders here. Prefix '
                         'folders with a + to indicate that they should be '
                         'searched recursive. If prefixed with an @ values '
                         'are read from file (one per line)')
    p_slide.add_argument('-p', '--profile', choices=list(PROFILES.keys()),
                         default='1080p', help='Output profile (default: '
                         '%(default)s)')
    p_slide.add_argument('--image-duration', type=int, default=5,
                         help='Duration for an image to show in seconds '
                         '(default: %(default)s)')
    p_slide.add_argument('--transition-duration', type=int, default=1,
                         help='Duration for the transition effect between '
                         'two images in seconds (default: %(default)s)')
    p_slide.add_argument('-f', '--font', default=DEFAULT_FONT,
                         help='Give a fontname or an absolute path to a '
                         '.ttf file here (default: %(default)s)')
    p_slide.add_argument('-t', '--title', default='', help='Title for the '
                         'slideshow (shown on the first slide)')
    p_slide.add_argument('-A', '--author', default='', help='Author of the '
                         'slideshow (shown on the last slide).')
    p_slide.add_argument('-e', '--epilog', default='', help='Epilog for the '
                         'slideshow (shown on the last slide, use `\\n` for '
                         'linebreaks)')
    p_slide.add_argument('--background', default='black',
                         help='Color behind text and images (default: '
                         '%(default)s)')
    p_slide.add_argument('--textcolor', default='white', help='Color for '
                         'text (default: %(default)s)')
    p_slide.add_argument('-w', '--workdir', default=None, help='Directory '
                         'for temporary files. If not given, the default '
                         'temporary directory of your system is used')
    p_slide.add_argument('-r', '--remove-tempfiles', action='store_false',
                         default=True, help='Clean temporary files and '
                         'directories when all work is done (default: '
                         '%(default)s)')
    p_slide.add_argument('-o', '--output', default='slideshow.mkv',
                         help='Name (and path) for the final output file '
                         '(default: %(default)s)')
    p_slide.add_argument('--convert', default=_convert, help='Path to '
                         'convert(.exe) binary (default: %(default)s)')
    p_slide.add_argument('--montage', default=_montage, help='Path to '
                         'montage(.exe) binary (default: %(default)s)')
    p_slide.add_argument('--mogrify', default=_mogrify, help='Path to '
                         'mogrify(.exe) binary (default: %(default)s)')
    p_slide.add_argument('--ffmpeg', default=_ffmpeg, help='Path to '
                         'ffmpeg(.exe) binary (default: %(default)s)')
    p_slide.add_argument('--mkvmerge', default=_mkv, help='Path to '
                         'mkvmerge(.exe) binary (default: %(default)s)')
    p_slide.set_defaults(func=_slideshow)
    args = p.parse_args()
    if args.version:
        print('ffmagick version {}'.format(__version__))
        sys.exit()
    args.func(args)


if __name__ == '__main__':
    main()
