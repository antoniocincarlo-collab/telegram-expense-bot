"""
export.py — Generazione PDF (reportlab) e CSV (pandas).
Crea report mensili con tabelle e grafici da inviare in chat Telegram.
"""
import io, logging, os, tempfile
from datetime import date
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Backend non-interattivo
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

logger = logging.getLogger(__name__)

# Colori per i grafici
COLORI = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7',
          '#DDA0DD', '#98D8C8', '#F7DC6F', '#BB8FCE', '#85C1E9']


async def genera_csv(group_id: int, anno: int, mese: int) -> io.BytesIO:
    """Genera un file CSV con le spese del mese."""
    import db
    spese = await db.get_spese_mese(group_id, anno, mese)

    if not spese:
        # CSV vuoto con intestazioni
        df = pd.DataFrame(columns=['Data', 'Importo', 'Descrizione', 'Categoria', 'Utente'])
    else:
        df = pd.DataFrame([{
            'Data': s['data'].strftime('%d/%m/%Y'),
            'Importo': float(s['importo']),
            'Descrizione': s['descrizione'],
            'Categoria': s['categoria'],
            'Utente': s['user_id']
        } for s in spese])

    buffer = io.BytesIO()
    df.to_csv(buffer, index=False, encoding='utf-8-sig')  # utf-8-sig per Excel
    buffer.seek(0)
    return buffer


async def genera_grafico_torta(group_id: int, anno: int, mese: int) -> io.BytesIO:
    """Genera un pie chart con la distribuzione per categoria."""
    import db
    totali = await db.get_totali_per_categoria(group_id, anno, mese)

    if not totali:
        return _grafico_vuoto("Nessuna spesa nel periodo")

    categorie = [t['categoria'] for t in totali]
    valori = [float(t['totale']) for t in totali]
    colori = COLORI[:len(categorie)]

    fig, ax = plt.subplots(1, 1, figsize=(8, 6))
    fig.patch.set_facecolor('#1a1a2e')

    wedges, texts, autotexts = ax.pie(
        valori, labels=categorie, autopct='%1.1f%%',
        colors=colori, startangle=90,
        textprops={'fontsize': 11, 'color': 'white'}
    )
    for at in autotexts:
        at.set_fontsize(10)
        at.set_color('white')
        at.set_fontweight('bold')

    totale = sum(valori)
    ax.set_title(f"Spese {mese:02d}/{anno} — Totale: €{totale:.2f}",
                 fontsize=14, color='white', fontweight='bold', pad=20)

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf


async def genera_grafico_budget(group_id: int) -> io.BytesIO:
    """Genera un grafico a barre con lo stato dei budget."""
    import budgets as bdg
    risultati = await bdg.controlla_tutti_budget(group_id)

    if not risultati:
        return _grafico_vuoto("Nessun budget impostato")

    categorie = [r['categoria'] for r in risultati]
    percentuali = [min(r['percentuale'], 120) for r in risultati]

    fig, ax = plt.subplots(figsize=(10, max(4, len(categorie) * 0.8)))
    fig.patch.set_facecolor('#1a1a2e')
    ax.set_facecolor('#16213e')

    colori_barre = []
    for p in percentuali:
        if p >= 100:
            colori_barre.append('#FF6B6B')
        elif p >= 75:
            colori_barre.append('#FFEAA7')
        elif p >= 50:
            colori_barre.append('#45B7D1')
        else:
            colori_barre.append('#4ECDC4')

    y_pos = range(len(categorie))
    bars = ax.barh(y_pos, percentuali, color=colori_barre, height=0.6, edgecolor='white', linewidth=0.5)

    ax.set_yticks(y_pos)
    ax.set_yticklabels(categorie, fontsize=11, color='white')
    ax.set_xlabel('% Budget Utilizzato', fontsize=11, color='white')
    ax.set_title('Stato Budget Mensili', fontsize=14, color='white', fontweight='bold')
    ax.axvline(x=100, color='#FF6B6B', linestyle='--', alpha=0.7, linewidth=1.5)
    ax.tick_params(colors='white')
    ax.spines['bottom'].set_color('white')
    ax.spines['left'].set_color('white')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    # Etichette sulle barre
    for bar, r in zip(bars, risultati):
        ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height()/2,
                f"€{r['speso']:.0f}/€{r['limite']:.0f}",
                va='center', fontsize=9, color='white')

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf


async def genera_pdf(group_id: int, anno: int, mese: int) -> io.BytesIO:
    """Genera un report PDF completo con tabelle e grafici."""
    import db
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                     Paragraph, Spacer, Image as RLImage)

    spese = await db.get_spese_mese(group_id, anno, mese)
    totali = await db.get_totali_per_categoria(group_id, anno, mese)
    totale_mese = await db.get_totale_mese(group_id, anno, mese)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            topMargin=20*mm, bottomMargin=20*mm)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('CustomTitle', parent=styles['Title'],
                                  fontSize=18, textColor=colors.HexColor('#2c3e50'))
    subtitle_style = ParagraphStyle('Subtitle', parent=styles['Heading2'],
                                     fontSize=13, textColor=colors.HexColor('#34495e'))

    elements = []

    # Titolo
    elements.append(Paragraph(f"Report Spese — {mese:02d}/{anno}", title_style))
    elements.append(Spacer(1, 10*mm))

    # Riepilogo
    elements.append(Paragraph(f"Totale mese: €{totale_mese:.2f}", subtitle_style))
    elements.append(Paragraph(f"Numero transazioni: {len(spese)}", styles['Normal']))
    elements.append(Spacer(1, 8*mm))

    # Tabella totali per categoria
    if totali:
        elements.append(Paragraph("Riepilogo per categoria", subtitle_style))
        data_cat = [['Categoria', 'Totale', 'N. Spese', '% Totale']]
        for t in totali:
            perc = (float(t['totale']) / totale_mese * 100) if totale_mese > 0 else 0
            data_cat.append([
                t['categoria'],
                f"€{float(t['totale']):.2f}",
                str(t['num_spese']),
                f"{perc:.1f}%"
            ])

        tab = Table(data_cat, colWidths=[120, 80, 70, 70])
        tab.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#2c3e50')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('FONTSIZE', (0,0), (-1,0), 11),
            ('FONTSIZE', (0,1), (-1,-1), 10),
            ('ALIGN', (1,0), (-1,-1), 'CENTER'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#ecf0f1')]),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING', (0,0), (-1,-1), 6),
        ]))
        elements.append(tab)
        elements.append(Spacer(1, 8*mm))

    # Grafico torta inline nel PDF
    try:
        pie_buf = await genera_grafico_torta(group_id, anno, mese)
        # Salva temporaneamente per reportlab
        tmp_pie = os.path.join(tempfile.gettempdir(), f"pie_{group_id}_{anno}_{mese}.png")
        with open(tmp_pie, 'wb') as f:
            f.write(pie_buf.read())
        elements.append(RLImage(tmp_pie, width=160*mm, height=120*mm))
        elements.append(Spacer(1, 5*mm))
    except Exception as e:
        logger.warning(f"Grafico torta non generato per PDF: {e}")

    # Dettaglio spese
    if spese:
        elements.append(Paragraph("Dettaglio spese", subtitle_style))
        data_spese = [['Data', 'Importo', 'Descrizione', 'Categoria']]
        for s in spese[:50]:  # Limita a 50 per il PDF
            desc = s['descrizione'][:40] + ('...' if len(s['descrizione']) > 40 else '')
            data_spese.append([
                s['data'].strftime('%d/%m'),
                f"€{float(s['importo']):.2f}",
                desc,
                s['categoria']
            ])

        tab2 = Table(data_spese, colWidths=[50, 70, 200, 80])
        tab2.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#2c3e50')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('FONTSIZE', (0,0), (-1,-1), 9),
            ('ALIGN', (1,0), (1,-1), 'CENTER'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#ecf0f1')]),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('TOPPADDING', (0,0), (-1,-1), 4),
        ]))
        elements.append(tab2)

    doc.build(elements)
    buffer.seek(0)

    # Cleanup file temporanei
    try:
        os.remove(tmp_pie)
    except Exception:
        pass

    return buffer


def _grafico_vuoto(messaggio: str) -> io.BytesIO:
    """Genera un'immagine con messaggio per grafici senza dati."""
    fig, ax = plt.subplots(figsize=(8, 4))
    fig.patch.set_facecolor('#1a1a2e')
    ax.set_facecolor('#1a1a2e')
    ax.text(0.5, 0.5, messaggio, transform=ax.transAxes,
            ha='center', va='center', fontsize=16, color='white')
    ax.axis('off')
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf
