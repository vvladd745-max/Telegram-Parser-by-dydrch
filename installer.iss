; Установщик для Inno Setup. Собирается так (из корня проекта):
;   "C:\Users\<имя>\AppData\Local\Programs\Inno Setup 6\ISCC.exe" installer.iss
; Перед этим должна быть готова сборка: pyinstaller digest.spec --noconfirm
;
; Два решения, которые здесь важнее прочих:
;   1. Ставим без прав администратора, в папку пользователя. Коллеге на рабочем
;      ноутбуке админ может быть недоступен, а программе он и не нужен.
;   2. При удалении НЕ трогаем данные человека в %LOCALAPPDATA%\TelegramDigest:
;      там настройки, вход в Telegram и закладки по каналам. Переустановка
;      не должна стирать месяцы накопленного состояния.

#define AppName "Парсер Telegram-каналов"
#define AppVersion "1.0"
#define AppExe "Парсер Telegram-каналов.exe"
#define BuildDir "dist\Парсер Telegram-каналов"

[Setup]
; Этот номер связывает установку с обновлениями и удалением. Менять нельзя:
; после смены Windows посчитает новую версию отдельной программой.
AppId={{8F3A6C51-2D94-4E7B-9C18-5A0E4B7D2F63}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; ставим в профиль пользователя — прав администратора не потребуется
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=installer
OutputBaseFilename=TelegramChannelParser-{#AppVersion}-setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; программа 64-битная, как и Python, на котором собрана
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; \
    GroupDescription: "Ярлыки:"

[Files]
; вся папка сборки целиком, вместе со служебной _internal
Source: "{#BuildDir}\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Удалить {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Запустить {#AppName}"; \
    Flags: nowait postinstall skipifsilent

; Раздела [UninstallDelete] здесь намеренно нет: данные пользователя лежат
; в %LOCALAPPDATA%\TelegramDigest и при удалении программы остаются на месте.
