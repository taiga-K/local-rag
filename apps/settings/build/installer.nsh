!macro customUnInstall
  MessageBox MB_YESNO|MB_DEFBUTTON2 "PostgreSQL のデータボリュームも削除しますか？$\nいいえを選ぶと、そのボリュームだけ残します。リポジトリのフォルダは消しません。" /SD IDNO IDYES deletePg IDNO keepPg
  deletePg:
    nsExec::ExecToLog '"$INSTDIR\kbindex settings.exe" --uninstall-stack delete-postgres'
    Goto uninstallDone
  keepPg:
    nsExec::ExecToLog '"$INSTDIR\kbindex settings.exe" --uninstall-stack keep-postgres'
  uninstallDone:
!macroend
