"""Three evaluation results and the four diagnostic artifacts, directly from logs."""
from pathlib import Path
import reflex as rx
from .loader import load_run,list_runs
from . import views
from .diff import skill_diff,skill_text

LOGS=Path(__file__).resolve().parents[3]/'logs'/'skillaxe'
TABLES={
    'table':lambda *children:rx.el.table(*children,width='100%',border_collapse='collapse',margin='1rem 0',font_size='0.9rem'),
    'th':lambda *children:rx.el.th(*children,text_align='left',padding='10px 14px',background='#f1f5ef',border_bottom='1px solid #dce4d7'),
    'td':lambda *children:rx.el.td(*children,padding='10px 14px',border_bottom='1px solid #e7ece4',vertical_align='top'),
}


class State(rx.State):
    runs:list[str]=[]
    selected:str=''
    tasks:list[str]=[]
    task:str=''
    question:str=''
    no_skill:str='미실행'
    initial:str='미실행'
    initial_title:str='초기 생성 스킬'
    initial_label:str='LLM이 생성한 L0 적용'
    evolved_label:str='진단으로 수정한 L1 후보 적용'
    evolved:str='미실행'
    outcome:str='아직 실행 결과가 없습니다.'
    error:str=''
    quality:str=''
    trigger:str=''
    compliance:str=''
    coverage:str=''
    initial_doc:str='초기 스킬 기록 없음'
    evolved_doc:str='진화 스킬 기록 없음'
    diff:str='변경 없음'
    baseline_sql:str=''
    initial_sql:str=''
    evolved_sql:str=''
    _data:dict={}

    @rx.event
    def refresh(self):
        self.runs=list_runs(LOGS)
        if self.runs:
            self.select_run(self.runs[-1])
        else:
            self._data={};self.selected='';self.tasks=[];self.task='';self.question=''
            self.no_skill=self.initial=self.evolved='미실행'
            self.outcome='아직 실행 결과가 없습니다.'
            for key in ('quality','trigger','compliance','coverage','initial_doc','evolved_doc','diff','baseline_sql','initial_sql','evolved_sql'):setattr(self,key,'기록 없음')

    @rx.event
    def select_run(self,name:str):
        if name not in list_runs(LOGS):return
        self.selected=name
        data=load_run(LOGS/name);self._data=data
        self.error='\n'.join(data['warnings'])
        self.no_skill=views.score(data,'no_skill');self.initial=views.score(data,'parent');self.evolved=views.score(data,'candidate')
        self.outcome=views.outcome(data)
        version=data['skills'].get('current',{}).get('version','L0')
        self.initial_title='초기 생성 스킬' if version=='L0' else '진화 전 스킬'
        self.initial_label=f'{version} 적용'
        self.evolved_label=data['skills'].get('candidate',{}).get('version','후보')+' 적용'
        self.initial_doc=skill_text(data['skills']['current']) if 'current' in data['skills'] else '기록 없음'
        self.evolved_doc=skill_text(data['skills']['candidate']) if 'candidate' in data['skills'] else '후보 미생성'
        self.diff=skill_diff(data['skills'])
        self.tasks=[t['task_id'] for t in data['tasks']]
        self.select_task(self.tasks[0] if self.tasks else '')

    @rx.event
    def select_task(self,name:str):
        if name and name not in self.tasks:return
        self.task=name;data=self._data
        self.question=next((t.get('question','') for t in data['tasks'] if t['task_id']==name),'진단 작업 기록 없음')
        for field,metric in [('quality','quality_impact'),('trigger','trigger_precision'),('compliance','instruction_compliance'),('coverage','solution_path_coverage')]:
            setattr(self,field,views.diagnostic_view(data,metric,name))
        self.baseline_sql=views.sql_view(data,'no_skill',name)
        self.initial_sql=views.sql_view(data,'parent',name)
        self.evolved_sql=views.sql_view(data,'candidate',name)


def score_card(number,title,value,subtitle):
    return rx.box(rx.text(number,color='#79936c',size='2',font_weight='700'),rx.heading(title,size='5',margin_top='0.6rem'),
        rx.text(value,font_size=['2.3rem','3rem'],font_weight='600',letter_spacing='-0.05em',margin_top='1rem'),rx.text(subtitle,color='#6d7d68',size='2'),
        border='1px solid #dfe6d9',border_radius='18px',padding='1.6rem',background='white',width='100%')


def document(text):
    return rx.markdown(text,component_map=TABLES)


def index():
    return rx.box(rx.vstack(
        rx.hstack(rx.text('SKILLAXE',font_weight='800',letter_spacing='0.15em',color='#44643a'),rx.spacer(),
                  rx.select(State.runs,value=State.selected,on_change=State.select_run,placeholder='실행 선택'),rx.icon_button('refresh-cw',on_click=State.refresh,variant='ghost',aria_label='실행 기록 새로고침'),width='100%',align='center'),
        rx.heading('스킬 적용 전과 후',size='8',letter_spacing='-0.04em'),
        rx.text('Validation 평가의 정답 수 / 전체 문제 수입니다. 각 조건은 독립 실행 1회입니다.',color='#697762',size='3'),
        rx.cond(State.error!='',rx.callout(State.error,color_scheme='amber',width='100%')),
        rx.grid(score_card('01','No skill',State.no_skill,'스킬 없이 실행'),score_card('02',State.initial_title,State.initial,State.initial_label),score_card('03','진화한 스킬',State.evolved,State.evolved_label),columns=rx.breakpoints(initial='1',sm='3'),spacing='4',width='100%'),
        rx.text(State.outcome,size='3',font_weight='500'),
        rx.accordion.root(rx.accordion.item(header='초기 스킬과 진화한 스킬 보기',content=rx.tabs.root(
            rx.tabs.list(rx.tabs.trigger('진화 전',value='initial'),rx.tabs.trigger('진화 후',value='evolved'),rx.tabs.trigger('변경점',value='diff')),
            rx.tabs.content(document(State.initial_doc),value='initial'),rx.tabs.content(document(State.evolved_doc),value='evolved'),rx.tabs.content(rx.code_block(State.diff,language='diff'),value='diff'),default_value='diff')),
            collapsible=True,width='100%'),
        rx.separator(margin_y='0.8rem'),
        rx.heading('스킬 진화에 사용한 진단 결과',size='6'),
        rx.text('초기 스킬을 네 축으로 진단한 결과입니다. 수정 후 스킬을 다시 진단한 점수는 아닙니다.',color='#697762',size='2'),
        rx.hstack(rx.text('진단 작업',size='2'),rx.select(State.tasks,value=State.task,on_change=State.select_task,placeholder='작업 선택'),align='center'),
        rx.text(State.question,size='4',font_weight='500'),
        rx.tabs.root(
            rx.tabs.list(rx.tabs.trigger('품질 영향',value='quality'),rx.tabs.trigger('적용 조건',value='trigger'),rx.tabs.trigger('지침 준수',value='compliance'),rx.tabs.trigger('해결 경로',value='coverage'),flex_wrap='wrap'),
            *[rx.tabs.content(rx.box(document(content),padding='1.5rem',background='white',border='1px solid #e2e8dc',border_radius='12px',overflow_x='auto'),value=value,padding_top='1rem') for value,content in [('quality',State.quality),('trigger',State.trigger),('compliance',State.compliance),('coverage',State.coverage)]],
            default_value='quality',width='100%'),
        rx.accordion.root(rx.accordion.item(header='이 작업의 SQL 평가 결과 비교',content=rx.grid(
            rx.box(rx.heading('No skill',size='4'),document(State.baseline_sql),min_width='0'),rx.box(rx.heading('초기 스킬',size='4'),document(State.initial_sql),min_width='0'),rx.box(rx.heading('진화 스킬',size='4'),document(State.evolved_sql),min_width='0'),columns=rx.breakpoints(initial='1',lg='3'),spacing='4')),
            collapsible=True,width='100%'),
        rx.text('각 조건은 독립 실행 1회입니다. SQL 실행 성공과 정답은 다르며, 진단 점수는 정답률이 아닙니다.',size='1',color='#798470'),
        width='100%',max_width='1180px',margin='0 auto',padding=['1.2rem','2.5rem'],spacing='5',align='stretch'),background='#f8faf5',min_height='100vh',color='#263820')

app=rx.App(theme=rx.theme(appearance='light',accent_color='grass',radius='large'))
app.add_page(index,title='SkillAxe · 스킬 적용 전과 후',on_load=State.refresh)
