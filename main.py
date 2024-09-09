from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, Label, Button, TabbedContent, TabPane, Tabs, Tab, Input, LoadingIndicator
from textual import events, on
from textual.containers import Horizontal, Center, Container, HorizontalScroll, VerticalScroll, Vertical
from textual.color import Color
import textual_slider
import dotenv; dotenv.load_dotenv()
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from time import sleep
from threading import Thread
from urllib.parse import quote_plus
from pprint import pprint
import requests
from lrctoolbox import SyncedLyrics
import cutlet
katsu = cutlet.Cutlet()
def is_cjk(string):
    return any([any([start <= ord(char) <= end for start, end in 
                [(4352, 4607), (11904, 42191), (43072, 43135), (44032, 55215), 
                 (63744, 64255), (65072, 65103), (65381, 65500), 
                 (131072, 196607)]
                ]) for char in string])
lrchead = {'User-Agent': 'SpotifyTUI/0.0.2 (https://github.com/mgytr/SpotifyTUI)'}
def scale_value(x, max_value=40, target_max=100):
    return (x / max_value) * target_max

def get_lyrics(playing: dict, artists=True):
    artistname, songname = ", ".join([x["name"] for x in playing["item"]["artists"] if x.get("name")]), playing["item"]["name"]
    if artists: r = requests.get(f'https://lrclib.net/api/search?artist_name={quote_plus(artistname)}&track_name={quote_plus(songname)}', headers=lrchead)
    else: r = requests.get(f'https://lrclib.net/api/search?track_name={quote_plus(songname)}', headers=lrchead)
    if len(r.json()) > 0:
        lyrics = (r.json()[0].get('syncedLyrics') or r.json()[0].get('plainLyrics')) if not r.json()[0]['instrumental'] else 'No lyrics found. Sorry!'
        
        plain = not lyrics.startswith('[')
        if not plain:
            lyrics = SyncedLyrics.load_from_lines(lyrics.splitlines())
        return lyrics, plain
    elif artists:
        return get_lyrics(playing, False)
    return '', True
def get_closest(seconds: float, lyrics: SyncedLyrics, time_range: float = 0.05):
    # Convert seconds to milliseconds
    target_time = seconds * 1000

    # Initialize variable to keep track of the current and next lyrics
    closest_lyric = None
    next_lyric = None
    lst = list(lyrics)
    # Iterate over all lyrics
    for i, lyric in enumerate(lyrics):
        # Get the timestamp of the current lyric
        lyric_time = lyric.timestamp
        next_lyric_time = lst[i + 1].timestamp if i + 1 < len(lyrics.synced_lines) else float('inf')

        # Case 1: The lyric timestamp is within range of the current time (target_time)
        if lyric_time <= target_time < next_lyric_time:
            closest_lyric = lyric

        # Case 2: The next lyric occurs after the target time
        if lyric_time > target_time and lyric_time - target_time <= time_range * 1000:
            next_lyric = lyric
            break

    # Return the closest current lyric or the next lyric within the range
    return closest_lyric or next_lyric
        
scope = "playlist-read-private,user-read-playback-state,user-modify-playback-state"
sp = spotipy.Spotify(client_credentials_manager=SpotifyOAuth(scope=scope))
# Shows playing devices
devices = sp.devices()
if len(devices) < 1:
    raise Exception('Must have at least one device')
nowplaying = sp.currently_playing()
if not nowplaying:
    raise Exception('Play something first')
class ControlBar(Static):
    def compose(self) -> ComposeResult:
        with Horizontal() as container:
            if self.app.playing:
                isplaying = self.app.playing['is_playing']
            else: 
                isplaying = False
            prevbtn = Button('<', id='backbtn')
            playbtn = Button('❚❚' if isplaying else ' ▷ ', id='playbtn')
            nextbtn = Button('>', id='nextbtn')
            slider = textual_slider.Slider(0, 40, id='timeslide')
            if self.app.playing:
                text = f'{self.app.playing["item"]["name"]}\n\n[bright_black]{", ".join([x["name"] for x in self.app.playing["item"]["artists"] if x.get("name")])}[/]'
            else:
                text = f'no music\n\n[bright_black][/]'
            lbl = Label(text, id='nameandartists')
            yield prevbtn
            yield playbtn
            yield nextbtn
            yield slider
            yield lbl
            
        yield container  # Yield the container
    @on(textual_slider.Slider.Changed)
    def sliderupdate(self) -> None:
        if self.app.bysync:
            self.app.bysync = False
            return

        elem = self.get_child_by_type(Horizontal).get_child_by_id('timeslide')
        try:
            ms = scale_value(elem.value, 40, self.app.playing['item']['duration_ms'])
        except TypeError: return
        def func(ms, elem):
            sleep(0.4)
            if elem._grabbed: return
            sp.seek_track(int(ms))
        Thread(target=func, args=(ms, elem)).start()

    
    def on_button_pressed(self, event: Button.Pressed):
        try:
            timeslide = self.get_child_by_type(Horizontal).get_child_by_id('timeslide')
            if event.button.id == 'playbtn':
                if self.app.playing['is_playing']:
                    try: sp.pause_playback()
                    except: pass
                else:
                    try: sp.start_playback()
                    except: pass
            lyric = self.app.get_child_by_type(Main).get_child_by_id('lyric')
            
            if event.button.id == 'backbtn':
                try: 
                    sp.previous_track()
                    lyric.update('Loading lyrics...')
                    timeslide._grabbed = True
                    sleep(0.01)
                    lyric.update('Loading lyrics...')
                    timeslide.value = 0
                    sleep(0.01)
                    timeslide._grabbed = False
                except: pass
            if event.button.id == 'nextbtn':
                try: 
                    sp.next_track()
                    lyric.update('Loading lyrics...')
                    timeslide._grabbed = True
                    sleep(0.01)
                    lyric.update('Loading lyrics...')
                    timeslide.value = 0
                    sleep(0.01)
                    timeslide._grabbed = False
                    
                except: pass
        except TypeError:
            pass

class Main(Static):
    def compose(self):
        yield Tabs(Tab('playlists', id='playliststab'), Tab('lyrics', id='lyrictab'))
        with Container(id='playlists', classes="active"):
            playlists = sp.current_user_playlists()
            with TabbedContent(*[x['name'] for x in playlists['items']]):
                """with TabPane('search'):
                    yield Input(placeholder='search...', id='searchinp')
                    yield LoadingIndicator(classes='searchload')
                    with VerticalScroll(classes='searchcontent'):
                        for _ in range(20): Button('Imagine Dragons - Beliver')
                """
                for p in playlists['items']:
                    tracks = sp.playlist_tracks(p['id'], limit=100)
                    with TabPane(p['name']):
                        with Horizontal():
                            playbtn = Button('  ▷   ', classes='playlist')
                            playbtn.uri = p['uri']
                            shufflebtn =  Button('  ⇆   ', classes='shufflelist')
                            shufflebtn.playlist = p
                            
                            yield playbtn
                        with VerticalScroll(classes='scrollsongs'):
                            for ip, track in enumerate([x['track'] for x in tracks['items']]):
                                btn = Button(", ".join([x["name"] for x in track["artists"] if x.get("name")]) + ' - '+track['name'], classes='song')
                                btn.track = track
                                btn.uri = p['uri']
                                btn.index = ip
                                yield btn
        yield Label('Loading lyrics...', id='lyric')
    def on_input_changed(self, event: Input.Changed):
        if event.input.id == 'searchinp':
            sp.search(event.input.value, type='track,album')
    def on_button_pressed(self, event: Button.Pressed):
        if event.button.has_class('song'):
            lyric = self.get_child_by_id('lyric')
            timeslide = self.app.get_child_by_type(ControlBar).get_child_by_type(Horizontal).get_child_by_id('timeslide')
            lyric.update('Loading lyrics...')
            self.app.lyrics = (None, None, ((), False))
            sp.start_playback(context_uri=event.button.uri, offset={'position': event.button.index})
            lyric.update('Loading lyrics...')
            timeslide._grabbed = True
            sleep(0.01)
            lyric.update('Loading lyrics...')
            timeslide.value = 0
            sleep(0.01)
            timeslide._grabbed = False
        if event.button.has_class('playlist'):
            lyric = self.get_child_by_id('lyric')
            timeslide = self.app.get_child_by_type(ControlBar).get_child_by_type(Horizontal).get_child_by_id('timeslide')
            lyric.update('Loading lyrics...')
            self.app.lyrics = (None, None, ((), False))
            sp.start_playback(context_uri=event.button.uri)
            lyric.update('Loading lyrics...')
            timeslide._grabbed = True
            sleep(0.01)
            lyric.update('Loading lyrics...')
            timeslide.value = 0
            sleep(0.01)
            timeslide._grabbed = False
        """if event.button.has_class('shufflelist'):
            sp.shuffle()"""
    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        try:
            elem = self.query_one('.active')
            elem.remove_class('active')
            elem.styles.display = 'none'
        except: pass
        if event.tab.id == 'lyrictab':
            elem = self.get_child_by_id('lyric')
            elem.add_class('active')
            elem.styles.display = 'block'
        if event.tab.id == 'playliststab':
            elem = self.get_child_by_id('playlists')
            elem.add_class('active')
            elem.styles.display = 'block'

class Spotify(App):
    """A Textual app to manage stopwatches."""

    BINDINGS = [("d", "toggle_dark", "Toggle dark mode")]
    CSS_PATH = 'main.tcss'
    lyrics = (None, None, ('', True))

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Main()
        yield ControlBar()
        yield Footer()

    def action_toggle_dark(self) -> None:
        """An action to toggle dark mode."""
        self.dark = not self.dark
    playing = {'is_playing': True, 'name': 'not playing', 'artists': []}
    gettinglrc = False
    def getlrc(self, artists, songname):
        self.gettinglrc = True
        self.query_one('#lyric').update('Loading lyrics...')
        lyrics = (artists, songname, get_lyrics(self.playing))
        songname = self.playing['item']['name']
        artists = ", ".join([x["name"] for x in self.playing["item"]["artists"] if x.get("name")])
        if artists == lyrics[0] and songname == lyrics[1]:
            self.lyrics = lyrics
            self.query_one('#lyric').update('(music)')
        self.gettinglrc = False
    def infoloop(self):
        firsttime = True
        while True:
            self.playing = sp.currently_playing()
            if firsttime:
                firsttime = False
                sleep(3)
            if not self.playing:
                continue
            self.update_ui()
            sleep(0.09)

    def timeloop(self):
        # Get the label to update with lyrics
        while 1:
            try:
                elem = self.query_one('#lyric')
                break
            except:
                pass
            sleep(0.01)

        last_displayed_lyric = None  # Track the last lyric displayed
        while 1:
            while self.playing == {'is_playing': True, 'name': 'not playing', 'artists': []} or not self.playing['is_playing']:
                pass

            # Increment the time as the song progresses (in seconds)
            self.time = self.playing['progress_ms'] / 1000

            if not self.lyrics[2][1]:  # If lyrics are synced
                if not self.gettinglrc:
                    closest = get_closest(self.time, self.lyrics[2][0])
                    if closest and closest != last_displayed_lyric:

                        elem.update(f'[green bold]{closest.text if not is_cjk(closest.text) else f"{closest.text} ({katsu.romaji(closest.text)})"}[/]')  # Update the label with the new lyric
                        last_displayed_lyric = closest  # Remember the last lyric displayed
            else:
                elem.update(self.lyrics[2][0])  # If no synced lyrics, just display the plain ones
            sleep(0.05)  # Small delay to prevent too many updates

    time = 0
    bysync = False
    def update_ui(self):
        control_bar = self.get_child_by_type(ControlBar).get_child_by_type(Horizontal)
        if control_bar:
            self.time = self.playing['progress_ms']/1000
            songname = self.playing['item']['name']
            artists = ", ".join([x["name"] for x in self.playing["item"]["artists"] if x.get("name")])
            play_button = control_bar.get_child_by_id('playbtn')
            if play_button:
                play_button.label = ' ▷ ' if not self.playing['is_playing'] else '❚❚'
            name_and_artists = control_bar.get_child_by_id('nameandartists')
            if (self.lyrics[0] != artists or self.lyrics[1] != songname):
                self.gettinglrc = True
                self.lyrics = (artists, songname, ((), False))
                Thread(target=self.getlrc, args=(artists, songname), daemon=True).start()
                
            if name_and_artists:
                name_and_artists.update(f'{songname}\n\n[bright_black]{artists}[/]')
            timeslider = control_bar.get_child_by_id('timeslide')
            if not timeslider._grabbed:
                self.bysync = True
                timeslider.value = scale_value(self.playing['progress_ms'], self.playing['item']['duration_ms'], 40)
            

    def startloops(self):
        Thread(target=self.infoloop, daemon=True).start()
        Thread(target=self.timeloop, daemon=True).start()



if __name__ == "__main__":
    app = Spotify()
    app.startloops()
    while app.playing == {'is_playing': True, 'name': 'not playing', 'artists': []}:
        pass
    app.run()
    
