from pathlib import Path
import json, shutil
root=Path.cwd()
def replace(path,old,new):
 p=root/path;s=p.read_text();assert s.count(old)==1,(path,s.count(old));p.write_text(s.replace(old,new))
replace('apps/desktop/src/app/skills/plugins-tab.tsx',"import { mergePluginPackages, type PackageKind, type PluginPackage } from './plugin-packages'", "import { KanbanToolsetControl } from './kanban-toolset-control'\nimport { mergePluginPackages, type PackageKind, type PluginPackage } from './plugin-packages'")
replace('apps/desktop/src/app/skills/plugins-tab.tsx','''  scopeLabel,
  busy,
''','''  scopeLabel,
  toolsetProfile,
  busy,
''')
replace('apps/desktop/src/app/skills/plugins-tab.tsx','''  scopeLabel: string
  busy: boolean
''','''  scopeLabel: string
  toolsetProfile: ProfileScope
  busy: boolean
''')
replace('apps/desktop/src/app/skills/plugins-tab.tsx',"          {(desktop?.status === 'error' ? desktop.error : pkg.description) && (",'''          {desktop?.id === 'kanban' && (
            <div className="mt-0.5 text-[length:var(--conversation-caption-font-size)] text-(--ui-text-tertiary)">
              {p.kanbanToolsHint}
            </div>
          )}
          {(desktop?.status === 'error' ? desktop.error : pkg.description) && (''')
replace('apps/desktop/src/app/skills/plugins-tab.tsx',"        ) : pkg.agentMissingInProfile && desktop ? (",'''        ) : desktop?.id === 'kanban' ? (
          <KanbanToolsetControl profile={toolsetProfile} scopeLabel={scopeLabel} />
        ) : pkg.agentMissingInProfile && desktop ? (''')
replace('apps/desktop/src/app/skills/plugins-tab.tsx','''                scopeLabel={label}
''','''                scopeLabel={label}
                toolsetProfile={profile}
''')
replace('apps/desktop/src/app/skills/index.tsx',"import { $skillsSortDesc, $toolsetsSortDesc } from './store'", "import { $skillsSortDesc, $toolsetsSortDesc, SKILLS_QUERY_KEY, TOOLSETS_QUERY_KEY } from './store'")
p=root/'apps/desktop/src/app/skills/index.tsx';s=p.read_text();start=s.index('// Skills + toolsets live in the RQ cache');end=s.index('// Per-tool call counts',start);keys=s[start:end];p.write_text(s[:start]+s[end:]);p=root/'apps/desktop/src/app/skills/store.ts';p.write_text((p.read_text()+'\n'+keys).rstrip()+'\n')
strings={
'en': ["The Desktop switch shows the board. The Agent switch grants Kanban tools to this profile’s CLI and Desktop chats; it does not start the dispatcher.","This backend does not expose Kanban in the tool configurator. Update Hermes on the selected backend to enable agent tools here.","Update backend","Kanban tools saved for ${profile}. Open a new chat to apply; existing chats are unchanged."],
'ru': ["Переключатель Desktop показывает доску. Переключатель агента разрешает инструменты Kanban в CLI и Desktop этого профиля; диспетчер при этом не запускается.","Этот backend не показывает Kanban в настройках инструментов. Обновите Hermes на выбранном backend, чтобы включить инструменты агента здесь.","Обновите backend","Инструменты Kanban сохранены для ${profile}. Откройте новый чат для применения; существующие чаты не изменятся."],
'zh': ["Desktop 开关控制看板界面。Agent 开关为此配置的 CLI 和 Desktop 聊天启用 Kanban 工具，不会启动调度器。","此后端的工具配置器尚未提供 Kanban。请更新所选后端上的 Hermes，然后在此启用智能体工具。","更新后端","已为 ${profile} 保存 Kanban 工具设置。新建聊天后生效；现有聊天保持不变。"],
'zh-hant': ["Desktop 開關控制看板介面。Agent 開關為此設定檔的 CLI 和 Desktop 聊天啟用 Kanban 工具，不會啟動排程器。","此後端的工具設定尚未提供 Kanban。請更新所選後端上的 Hermes，再於此啟用代理工具。","更新後端","已為 ${profile} 儲存 Kanban 工具設定。建立新聊天後生效；現有聊天保持不變。"],
'ja': ["Desktop スイッチはボードを表示します。Agent スイッチは、このプロファイルの CLI と Desktop チャットに Kanban ツールを許可します。ディスパッチャーは起動しません。","このバックエンドのツール設定には Kanban がありません。選択したバックエンドの Hermes を更新すると、ここでエージェントのツールを有効にできます。","バックエンドを更新","${profile} の Kanban ツール設定を保存しました。新しいチャットで適用されます。既存のチャットは変更されません。"],
'ar': ["يعرض مفتاح Desktop اللوحة. يمنح مفتاح Agent أدوات Kanban لمحادثات CLI وDesktop لهذا الملف الشخصي، ولا يشغّل موزّع المهام.","لا يعرض هذا الخادم Kanban في إعدادات الأدوات. حدّث Hermes على الخادم المحدد لتفعيل أدوات الوكيل من هنا.","حدّث الخادم","حُفظت إعدادات أدوات Kanban للملف ${profile}. افتح محادثة جديدة لتطبيقها؛ لن تتغير المحادثات الحالية."]}
for locale,v in strings.items():
 p=root/f'apps/desktop/src/i18n/{locale}.ts';s=p.read_text()
 addition=''.join('      '+k+': '+json.dumps(text,ensure_ascii=False)+',\n' for k,text in zip(('kanbanToolsHint','kanbanToolsUnavailable','kanbanToolsUpdateBackend'),v))
 addition+='      kanbanToolsSaved: (profile: string) => `'+v[3]+'`,\n'
 start=s.index('  skills: {')+len('  skills: {');end=s.index('\n  },',start);section=s[start:end]
 if '    plugins: {' in section:
  i=start+section.index('    plugins: {')+len('    plugins: {');s=s[:i]+'\n'+addition+s[i:]
 else: s=s[:start]+'\n    plugins: {\n'+addition+'    },'+s[start:]
 p.write_text(s)
p=root/'apps/desktop/src/i18n/types.ts';s=p.read_text();i=s.index('      legacyBackend: string',s.index('  skills:'));s=s[:i]+'''      kanbanToolsHint: string
      kanbanToolsUnavailable: string
      kanbanToolsUpdateBackend: string
      kanbanToolsSaved: (profile: string) => string
'''+s[i:];p.write_text(s)
for name in ('kanban-toolset-control.tsx','plugins-tab-kanban.test.tsx'):
 shutil.copyfile(Path(__file__).with_name(name),root/'apps/desktop/src/app/skills'/name)
