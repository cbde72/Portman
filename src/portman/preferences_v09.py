"""Stable table identities, per-column preferences and interactive charts."""
from PySide6.QtCore import Qt,SIGNAL
from PySide6.QtWidgets import QTableView,QMenu,QCheckBox
from .widgets_v09 import table_tools

TABLE_FONT_OWNERS={'positions':'positions','dashboard':'dashboard','history_widget':'history','market_widget':'market','performance_widget':'performance','quality_widget':'quality'}
def table_font_type(key): return TABLE_FONT_OWNERS.get(key.split('.')[0])
POSITION_COLUMNS=('security','name','asset_type','region','capitalization','quantity','cost_eur','value_eur','profit_eur','dividend_percent','dividend_eur','share_percent','profit_percent','symbol','wkn','first_activity')
TABLE_COLUMNS={
    'dashboard.top':('security','asset_type','value_eur','share_percent','profit_eur'),
    'quality_widget.table':('severity','area','identifier','subject','message'),
    'history_widget.wealth_table':('month','total','cash','deposit','securities','retirement','property','debt'),
    'history_widget.diff':('depot','security','name','before','after','change','units_change','status'),
    'history_widget.tx':('day','depot','external_id','kind','security','amount','source','purpose'),
    'history_widget.audit':('import_id','status','imported_at','path','notes'),
    'history_widget.bank_archive.bookings':('day','value_day','account','amount','currency','counterparty','purpose'),
    'history_widget.bank_archive.documents':('document_id','day','account','title','size_kb'),
    'history_widget.state_history.table':('day','stored_at','account','kind','value','status','import_id'),
    'market_widget.table':('security','symbol','price','currency','year_percent','volatility_percent','quote_time','status','source'),
    'market_widget.metrics':('metric','value','source','as_of'),
    'market_widget.dividend_table':('security','ex_day','pay_day','amount','currency','status','retrieved_at'),
    'market_widget.history_table':('retrieved_at','source','symbol','price','currency'),
    'performance_widget.comparison':('period','start','end','end_value','profit','value_change','dietz','dietz_annual','xirr'),
}


class TablePreferences:
    def __init__(self,window):
        self.window=window; self.tables={}
        # Attribute identities survive widget order and translated column captions.
        owners=[('main',window)]+[(name,value) for name,value in vars(window).items() if name.endswith('_widget') or name=='dashboard']
        for name in ('bank_archive','state_history'):
            owners.append(('history_widget.'+name,getattr(window.history_widget,name)))
        for owner_name,owner in owners:
            for name,value in vars(owner).items():
                if isinstance(value,QTableView): self.tables[owner_name+'.'+name]=value
        for category,table in window.tables.items(): self.tables['positions.'+category]=table
        saved=window.settings.get('tables_v09',{})
        for key,table in self.tables.items():
            table_tools(table); header=table.horizontalHeader(); header.setSectionsMovable(True)
            font_type=table_font_type(key)
            if font_type: table.setProperty('table_type',font_type)
            columns=POSITION_COLUMNS if key.startswith('positions.') else TABLE_COLUMNS.get(key)
            if columns is None: continue
            table.setProperty('column_ids_v09',columns)
            record=saved.get(key,{})
            if key.startswith('positions.') and 'symbol_wkn' in record:
                record = {column: dict(state) for column, state in record.items()}
                combined = record.pop('symbol_wkn')
                order = combined.get('order', 13)
                for state in record.values():
                    if state.get('order', 0) > order: state['order'] += 1
                record.setdefault('symbol', dict(combined))
                record.setdefault('wkn', {**combined, 'order': order + 1})
            default_order = list(columns)
            if key.startswith('positions.') and not record:
                default_order.remove('symbol'); default_order.insert(1, 'symbol')
                default_order.remove('wkn'); default_order.insert(2, 'wkn')
                default_order.remove('profit_percent'); default_order.insert(default_order.index('profit_eur') + 1, 'profit_percent')
            for logical,column in enumerate(columns):
                state=record.get(column,{})
                if 'width' in state: table.setColumnWidth(logical,max(30,min(1500,state['width'])))
                table.setColumnHidden(logical,state.get('hidden',False))
            for visual,column in enumerate(sorted(columns,key=lambda c:record.get(c,{}).get('order',default_order.index(c)))):
                header.moveSection(header.visualIndex(columns.index(column)),visual)
            table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            if table.receivers(SIGNAL('customContextMenuRequested(QPoint)')):
                table.customContextMenuRequested.disconnect()
            table.customContextMenuRequested.connect(lambda point,t=table:self.menu(t,point))
            # Column selection belongs on every header section as well as in
            # the table body; users should not have to aim below the heading.
            header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            if header.receivers(SIGNAL('customContextMenuRequested(QPoint)')):
                header.customContextMenuRequested.disconnect()
            header.customContextMenuRequested.connect(lambda point,t=table:self.menu(t,point,header=True))
    def menu(self,table,point,header=False):
        menu=QMenu(table)
        for c in range(table.model().columnCount()):
            action=menu.addAction(str(table.model().headerData(c,Qt.Orientation.Horizontal))); action.setCheckable(True); action.setChecked(not table.isColumnHidden(c))
            action.toggled.connect(lambda checked,column=c:table.setColumnHidden(column,not checked))
        target = table.horizontalHeader() if header else table.viewport()
        menu.exec(target.mapToGlobal(point))
    def save(self):
        self.window.settings['tables_v09']={key:{column:dict(width=t.columnWidth(i),hidden=t.isColumnHidden(i),order=t.horizontalHeader().visualIndex(i)) for i,column in enumerate(t.property('column_ids_v09'))} for key,t in self.tables.items() if t.property('column_ids_v09')}


def enhance_chart(widget,repo):
    from matplotlib.backends.backend_qtagg import NavigationToolbar2QT
    from matplotlib.dates import date2num,DateFormatter,AutoDateFormatter,ConciseDateFormatter
    from datetime import datetime
    canvas=getattr(widget,'canvas',None); figure=getattr(widget,'fig',None)
    if canvas is None or figure is None: return
    toolbar=NavigationToolbar2QT(canvas,widget); toolbar.setMaximumHeight(32); widget.layout().addWidget(toolbar)
    widget.setMinimumHeight(440)
    widget.setMaximumHeight(16777215)
    events=QCheckBox('Importereignisse anzeigen · Datum des Imports'); widget.layout().addWidget(events)
    state={'markers':[],'legend':{},'busy':False}
    def decorate(event=None):
        if state['busy']: return
        state['busy']=True
        try:
            for marker in state['markers']:
                try: marker.remove()
                except (ValueError,NotImplementedError): pass
            state['markers']=[]; state['legend']={}
            for axis in figure.axes:
                legend=axis.get_legend()
                if legend:
                    artists={a.get_label():a for a in axis.get_lines()}
                    for text in legend.get_texts():
                        line=artists.get(text.get_text())
                        if line is not None: text.set_picker(True); state['legend'][text]=line
                if events.isChecked() and isinstance(axis.xaxis.get_major_formatter(),(DateFormatter,AutoDateFormatter,ConciseDateFormatter)):
                    low,high=axis.get_xlim()
                    dates=repo.db.execute('SELECT DISTINCT substr(imported_at,1,10) FROM imports WHERE active=1').fetchall()
                    for row in dates:
                        try: x=date2num(datetime.fromisoformat(row[0]))
                        except ValueError: continue
                        if low<=x<=high: state['markers'].append(axis.axvline(x,color='#9a6bce',alpha=.35,linestyle=':',label='_import'))
        finally: state['busy']=False
    def pick(event):
        line=state['legend'].get(event.artist)
        if line is not None: line.set_visible(not line.get_visible()); event.artist.set_alpha(1 if line.get_visible() else .35); canvas.draw_idle()
    canvas.mpl_connect('draw_event',decorate); canvas.mpl_connect('pick_event',pick)
    events.toggled.connect(lambda: (decorate(),canvas.draw_idle()))
    widget._v09_chart=(toolbar,events,state)
