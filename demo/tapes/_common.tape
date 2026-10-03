# shared settings, included by every tape
Set Shell bash
Set FontFamily "JetBrainsMono Nerd Font"
Set FontSize 24
Set Width 1920
Set Height 1080
Set Padding 48
Set Theme { "background": "#0b0b0d", "foreground": "#e6e6e6", "cursor": "#8ab4f8", "black": "#0b0b0d", "red": "#ff6b6b", "green": "#6ee7a8", "yellow": "#ffd166", "blue": "#8ab4f8", "magenta": "#c792ea", "cyan": "#7fdbff", "white": "#e6e6e6", "brightBlack": "#5c5f66", "brightRed": "#ff8787", "brightGreen": "#8cf5c0", "brightYellow": "#ffe08a", "brightBlue": "#a9c7ff", "brightMagenta": "#dcb2ff", "brightCyan": "#a5ecff", "brightWhite": "#ffffff" }
Set TypingSpeed 28ms
Set Framerate 30
Set CursorBlink false
Hide
Type "export PSQLRC=/vhs/demo/psqlrc; clear" Enter
Type 'psql "$DB_URL" -q' Enter
Sleep 1500ms
Type "\! clear" Enter
Sleep 300ms
Show
