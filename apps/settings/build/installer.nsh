!macro customUnInstall
  ${ifNot} ${isUpdated}
    StrCpy $1 "0"
    MessageBox MB_YESNO|MB_DEFBUTTON2 "PostgreSQL のデータボリュームも削除しますか？$\nいいえを選ぶと、そのボリュームだけ残します。リポジトリのフォルダは消しません。" /SD IDNO IDYES deletePg IDNO runRemove
    deletePg:
      StrCpy $1 "1"
    runRemove:
      System::Call 'Kernel32::SetEnvironmentVariable(t, t)i ("KBINDEX_DELETE_POSTGRES", "$1")'
      nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$$keep=''kbindex_postgres_data''; $$delete=$$env:KBINDEX_DELETE_POSTGRES; function Invoke-Docker { param([string[]]$$a) if (Get-Command docker -ErrorAction SilentlyContinue) { & docker @$$a } else { & wsl.exe -e docker @$$a } }; Invoke-Docker @(''ps'',''-aq'',''--filter'',''label=com.docker.compose.project=kbindex'') | ForEach-Object { if ($$_) { Invoke-Docker @(''rm'',''-f'',$$_) } }; Invoke-Docker @(''volume'',''ls'',''-q'',''--filter'',''label=com.docker.compose.project=kbindex'') | ForEach-Object { if ($$delete -eq ''1'' -or $$_ -ne $$keep) { Invoke-Docker @(''volume'',''rm'',$$_) } }"'
  ${endIf}
!macroend
