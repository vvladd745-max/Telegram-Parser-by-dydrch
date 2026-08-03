; Установщик для Inno Setup. Собирается так (из корня проекта):
;   "C:\Users\<имя>\AppData\Local\Programs\Inno Setup 6\ISCC.exe" installer.iss
; Перед этим должна быть готова сборка: pyinstaller digest.spec --noconfirm
;
; Два решения, которые здесь важнее прочих:
;   1. Ставим без прав администратора, в папку пользователя. Коллеге на рабочем
;      ноутбуке админ может быть недоступен, а программе он и не нужен.
;   2. При удалении данные человека в %LOCALAPPDATA%\TelegramDigest — настройки,
;      вход в Telegram и закладки по каналам — сами по себе не стираются:
;      программа спрашивает об этом отдельно, и по умолчанию отвечает «нет».
;      Переустановка не должна стирать месяцы накопленного состояния.

#define AppName "Парсер Telegram-каналов"
#define AppVersion "1.0"
#define AppExe "Парсер Telegram-каналов.exe"
#define BuildDir "dist\Парсер Telegram-каналов"
; Имя программы для панели задач. Должно совпадать с APP_USER_MODEL_ID
; в digest\app.py — см. пояснение в разделе [Icons].
#define AppUserModelID "Dydrch.TelegramChannelParser"

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
; Страница выбора папки показывается ВСЕГДА. По умолчанию Inno Setup прячет её
; при повторной установке поверх старой — из-за этого человек, уже поставивший
; программу однажды, больше не видел выбора диска и папки.
DisableDirPage=no
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
; AppUserModelID — это имя, которым программа представляется панели задач.
; Оно должно совпадать с APP_USER_MODEL_ID в digest\app.py: по нему Windows
; понимает, что закреплённый ярлык и запущенное окно — одно и то же.
; Без совпадения на панели появятся две кнопки вместо одной.
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; \
    AppUserModelID: "{#AppUserModelID}"
Name: "{group}\Удалить {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon; \
    AppUserModelID: "{#AppUserModelID}"
; Ярлык удаления в самой папке программы. Inno Setup и так кладёт туда
; unins000.exe, но по такому имени человек ничего не найдёт.
Name: "{app}\Удалить {#AppName}"; Filename: "{uninstallexe}"; \
    IconFilename: "{uninstallexe}"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Запустить {#AppName}"; \
    Flags: nowait postinstall skipifsilent

; Раздела [UninstallDelete] здесь намеренно нет: данные пользователя лежат
; в %LOCALAPPDATA%\TelegramDigest, и сами по себе они не удаляются. Их судьбу
; решает человек в вопросе, который задаёт код ниже.

[Code]
const
  { Имя папки данных и имя хранилища секретов. Должны совпадать с APP_NAME
    в core\paths.py и SERVICE_DEFAULT в core\secrets.py: установщик знает
    эти имена сам, спросить их у программы ему негде.
    Написаны здесь, а не через #define, чтобы не зависеть от препроцессора:
    ошибку подстановки внутри кода не видно до самого удаления. }
  DataDirName = 'TelegramDigest';
  KeyringService = 'TelegramDigest';

{ Записи в Диспетчере учётных данных Windows. Библиотека keyring кладёт
  первый секрет под именем службы, а каждый следующий — под «секрет@служба».
  Поэтому убирать надо оба вида имён. Имена самих секретов взяты из
  SECRET_PATHS в core\settings.py.

  Похожие записи с хвостом (TelegramDigest-ПРОБА и подобные) остаются от
  проверочных запусков автора и здесь не трогаются: совпадение имени
  должно быть точным. }
procedure ForgetCredentials();
var
  Targets: array[0..3] of String;
  I, Code: Integer;
begin
  Targets[0] := KeyringService;
  Targets[1] := 'telegram.api_hash@' + KeyringService;
  Targets[2] := 'bot.token@' + KeyringService;
  Targets[3] := 'model.api_key@' + KeyringService;
  for I := 0 to 3 do
    { Отсутствующая запись — не ошибка, код возврата не проверяем. }
    Exec(ExpandConstant('{sys}\cmdkey.exe'), '/delete:' + Targets[I],
         '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

{ Вопрос задаётся ПОСЛЕ того, как файлы программы уже удалены: если человек
  передумает и закроет окно, программа всё равно будет снята, а данные целы.
  При тихом удалении (/SILENT) вопроса нет и данные остаются. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  if UninstallSilent then
    Exit;

  DataDir := ExpandConstant('{localappdata}') + '\' + DataDirName;
  if not DirExists(DataDir) then
    Exit;

  if MsgBox('Удалить также ваши настройки, вход в Telegram и закладки по каналам?'
            + #13#10#13#10
            + 'Они лежат в папке:' + #13#10 + DataDir + #13#10#13#10
            + 'Если собираетесь поставить программу заново — нажмите «Нет».'
            + ' Тогда всё сохранится и настраивать заново не придётся.',
            mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
  begin
    DelTree(DataDir, True, True, True);
    ForgetCredentials();
  end;
end;
