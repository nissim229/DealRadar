"""
whatif_calculator.py
The dark, live-updating What-If Calculator - a self-contained HTML/CSS/JS
component embedded via streamlit.components.v1.html. All math runs
client-side in JavaScript for instant updates with no server round-trip.
"""

def render_whatif_calculator_html(row_item, defaults, calc_target_yield):
    """Builds a self-contained, dark-themed, live-updating HTML/CSS/JS what-if
    calculator - custom styled sliders, tabular monospace numbers, and a target
    gauge - instead of stacked native Streamlit widgets. All math runs client-side
    in JS, so results update instantly with no server round-trip."""

    price = int(row_item['price'])
    down_pct = int(defaults.get('down_pct', 25))
    interest = float(defaults.get('interest', 6.5))
    rent = int(defaults.get('rent', 3500))
    vacancy = int(defaults.get('vacancy', 5))
    tax_rate = float(defaults.get('tax_rate', 1.2))
    ins_rate = float(defaults.get('ins_rate', 0.4))
    target = float(calc_target_yield)
    # Pre-fill with the listing's real HOA when RentCast provided one,
    # instead of always starting this slider at 0 and leaving it to the
    # user to notice and re-enter a number the app already has.
    hoa_default = row_item.get('hoa_monthly') or 0
    try:
        hoa_default = int(float(hoa_default))
    except (TypeError, ValueError):
        hoa_default = 0

    html = f"""
    <div id="wi-root">
    <style>
        #wi-root {{
            --bg: #0f172a;
            --panel: #16213a;
            --panel-2: #1c2942;
            --border: #2a3958;
            --text: #f1f5f9;
            --text-dim: #8fa0bd;
            --blue: #3b82f6;
            --green: #10b981;
            --amber: #fbbf24;
            --red: #f87171;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: var(--bg);
            border-radius: 14px;
            padding: 28px;
            color: var(--text);
        }}
        #wi-root * {{ box-sizing: border-box; }}
        .wi-grid {{ display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 28px; }}
        @media (max-width: 700px) {{ .wi-grid {{ grid-template-columns: 1fr; }} }}

        .wi-section {{ margin-bottom: 22px; }}
        .wi-section-title {{
            font-size: 11px; text-transform: uppercase; letter-spacing: 1px;
            color: var(--text-dim); font-weight: 600; margin-bottom: 14px;
            display: flex; align-items: center; gap: 8px;
        }}
        .wi-row {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px; }}
        .wi-label {{ font-size: 13px; color: var(--text-dim); }}
        .wi-value {{
            font-family: 'JetBrains Mono', 'SF Mono', Consolas, monospace;
            font-size: 14px; font-weight: 600; color: var(--text);
            font-variant-numeric: tabular-nums;
        }}
        .wi-field {{ margin-bottom: 0; }}
        .wi-field-grid {{ display: grid; gap: 18px; margin-bottom: 18px; }}
        .wi-field-grid-2 {{ grid-template-columns: 1fr 1fr; }}
        .wi-field-grid-3 {{ grid-template-columns: 1fr 1fr 1fr; }}
        @media (max-width: 480px) {{
            .wi-field-grid-2, .wi-field-grid-3 {{ grid-template-columns: 1fr; }}
        }}

        input[type=range] {{
            -webkit-appearance: none; width: 100%; height: 6px;
            border-radius: 3px; background: var(--panel-2); outline: none; margin-top: 6px;
        }}
        input[type=range]::-webkit-slider-thumb {{
            -webkit-appearance: none; width: 18px; height: 18px; border-radius: 50%;
            background: var(--blue); cursor: pointer; border: 2px solid #0f172a;
            box-shadow: 0 0 0 1px var(--blue);
        }}
        input[type=range]::-moz-range-thumb {{
            width: 18px; height: 18px; border-radius: 50%; background: var(--blue);
            cursor: pointer; border: 2px solid #0f172a;
        }}
        input[type=number], select {{
            width: 100%; background: var(--panel-2); border: 1px solid var(--border);
            color: var(--text); padding: 9px 11px; border-radius: 7px; font-size: 14px;
            font-family: 'JetBrains Mono', monospace; margin-top: 6px;
        }}
        input[type=number]:focus, select:focus {{ outline: none; border-color: var(--blue); }}

        .wi-results {{
            background: var(--panel); border: 1px solid var(--border); border-radius: 12px;
            padding: 20px; display: flex; flex-direction: column; align-items: center;
        }}
        .wi-cf-label {{ font-size: 11px; letter-spacing: 1px; color: var(--text-dim); font-weight: 600; }}
        .wi-cf-value {{
            font-family: 'JetBrains Mono', monospace; font-size: 42px; font-weight: 800;
            font-variant-numeric: tabular-nums; margin: 4px 0 10px 0; transition: color 0.2s;
        }}
        .wi-badge {{
            font-size: 12px; font-weight: 700; padding: 5px 14px; border-radius: 20px;
            margin-bottom: 18px;
        }}
        .wi-gauge-wrap {{ width: 100%; margin-bottom: 40px; }}
        .wi-mao-box {{
            width: 100%; background: rgba(59,130,246,0.1); border: 1px solid rgba(59,130,246,0.35);
            border-radius: 10px; padding: 12px 14px; margin-bottom: 18px; text-align: center;
        }}
        .wi-mao-label {{ font-size: 10px; color: var(--text-dim); letter-spacing: 0.5px; margin-bottom: 4px; }}
        .wi-mao-value {{ font-family: 'JetBrains Mono', monospace; font-size: 22px; font-weight: 800; color: var(--blue); }}
        .wi-mao-delta {{ font-size: 12px; color: var(--text-dim); margin-top: 4px; }}
        .wi-mao-apply {{
            margin-top: 8px; background: var(--blue); color: white; border: none;
            padding: 6px 16px; border-radius: 6px; font-size: 12px; font-weight: 600;
            cursor: pointer; font-family: 'Inter', sans-serif;
        }}
        .wi-mao-apply:hover {{ background: #2563eb; }}
        .wi-gauge-labels {{ display: flex; justify-content: space-between; font-size: 11px; color: var(--text-dim); margin-bottom: 5px; font-family: 'JetBrains Mono', monospace; }}
        .wi-gauge-track {{ position: relative; height: 10px; background: var(--panel-2); border-radius: 6px; overflow: visible; }}
        .wi-gauge-fill {{ height: 100%; border-radius: 6px; transition: width 0.25s ease, background 0.25s ease; }}
        .wi-gauge-target {{ position: absolute; top: -4px; width: 2px; height: 18px; background: var(--text); opacity: 0.7; }}
        .wi-gauge-target::after {{
            content: 'TARGET'; position: absolute; top: 22px; left: 50%; transform: translateX(-50%);
            font-size: 9px; color: var(--text-dim); letter-spacing: 0.5px; white-space: nowrap;
        }}

        .wi-metrics {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; width: 100%; }}
        @media (min-width: 460px) {{ .wi-metrics {{ grid-template-columns: 1fr 1fr 1fr; }} }}
        .wi-metrics-caption {{ font-size: 10px; color: var(--text-dim); text-align: center; margin-top: 10px; }}
        .wi-metric[title] {{ cursor: help; }}
        .wi-metric {{ background: var(--panel-2); border-radius: 8px; padding: 12px 14px; }}
        .wi-metric-label {{ font-size: 10px; color: var(--text-dim); letter-spacing: 0.5px; margin-bottom: 5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
        .wi-metric-value {{ font-family: 'JetBrains Mono', monospace; font-size: 17px; font-weight: 700; font-variant-numeric: tabular-nums; }}
    </style>

    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&family=JetBrains+Mono:wght@500;600;700;800&display=swap" rel="stylesheet">

    <div class="wi-grid">
        <div>
            <div class="wi-section">
                <div class="wi-section-title">💳 Financing</div>
                <div class="wi-field-grid wi-field-grid-2">
                    <div class="wi-field">
                        <div class="wi-row"><span class="wi-label">Offer Price</span><span class="wi-value" id="v-price">$0</span></div>
                        <input type="number" id="price" value="{price}" step="5000">
                    </div>
                    <div class="wi-field">
                        <div class="wi-row"><span class="wi-label">Down Payment</span><span class="wi-value" id="v-down">0%</span></div>
                        <input type="range" id="down" min="0" max="100" value="{down_pct}">
                    </div>
                </div>
                <div class="wi-field-grid wi-field-grid-2">
                    <div class="wi-field">
                        <div class="wi-row"><span class="wi-label">Interest Rate</span><span class="wi-value" id="v-interest">0%</span></div>
                        <input type="range" id="interest" min="0" max="12" step="0.125" value="{interest}">
                    </div>
                    <div class="wi-field">
                        <div class="wi-row"><span class="wi-label">Loan Term</span></div>
                        <select id="term">
                            <option value="10">10 years</option>
                            <option value="15">15 years</option>
                            <option value="20">20 years</option>
                            <option value="25">25 years</option>
                            <option value="30" selected>30 years</option>
                        </select>
                    </div>
                </div>
            </div>

            <div class="wi-section">
                <div class="wi-section-title">🏠 Income</div>
                <div class="wi-field-grid wi-field-grid-2">
                    <div class="wi-field">
                        <div class="wi-row"><span class="wi-label">Monthly Rent</span><span class="wi-value" id="v-rent">$0</span></div>
                        <input type="number" id="rent" value="{rent}" step="50">
                    </div>
                    <div class="wi-field">
                        <div class="wi-row"><span class="wi-label">Vacancy</span><span class="wi-value" id="v-vacancy">0%</span></div>
                        <input type="range" id="vacancy" min="0" max="20" value="{vacancy}">
                    </div>
                </div>
            </div>

            <div class="wi-section">
                <div class="wi-section-title">🧾 Ongoing Expenses</div>
                <div class="wi-field-grid wi-field-grid-2">
                    <div class="wi-field">
                        <div class="wi-row"><span class="wi-label">Property Management</span><span class="wi-value" id="v-mgmt">0%</span></div>
                        <input type="range" id="mgmt" min="0" max="15" value="0">
                    </div>
                    <div class="wi-field">
                        <div class="wi-row"><span class="wi-label">Maintenance Reserve</span><span class="wi-value" id="v-maint">0%</span></div>
                        <input type="range" id="maint" min="0" max="15" value="5">
                    </div>
                </div>
                <div class="wi-field-grid wi-field-grid-2">
                    <div class="wi-field">
                        <div class="wi-row"><span class="wi-label">HOA ($/month)</span><span class="wi-value" id="v-hoa">${hoa_default}</span></div>
                        <input type="number" id="hoa" value="{hoa_default}" step="25">
                    </div>
                </div>
            </div>

            <div class="wi-section">
                <div class="wi-section-title">💵 At Purchase</div>
                <div class="wi-field-grid wi-field-grid-2">
                    <div class="wi-field">
                        <div class="wi-row"><span class="wi-label">Closing Costs</span><span class="wi-value" id="v-closing">$0</span></div>
                        <input type="number" id="closing" value="0" step="500">
                    </div>
                    <div class="wi-field">
                        <div class="wi-row"><span class="wi-label">Target Return</span><span class="wi-value" id="v-target">0%</span></div>
                        <input type="range" id="target" min="1" max="20" step="0.5" value="{target}">
                    </div>
                </div>
            </div>
        </div>

        <div class="wi-results">
            <div class="wi-cf-label">MONTHLY CASH FLOW</div>
            <div class="wi-cf-value" id="cf-value">$0</div>
            <div class="wi-badge" id="badge">—</div>

            <div class="wi-mao-box">
                <div class="wi-mao-label">🎯 SUGGESTED MAX OFFER TO HIT YOUR TARGET</div>
                <div class="wi-mao-value" id="mao-value">$0</div>
                <div class="wi-mao-delta" id="mao-delta"></div>
                <button class="wi-mao-apply" id="mao-apply" style="display:none;">Apply this price</button>
            </div>

            <div class="wi-gauge-wrap">
                <div class="wi-gauge-labels"><span>0%</span><span id="gauge-coc-label">Cash-on-Cash ROI</span><span id="gauge-max">25%</span></div>
                <div class="wi-gauge-track">
                    <div class="wi-gauge-fill" id="gauge-fill" style="width:0%"></div>
                    <div class="wi-gauge-target" id="gauge-target" style="left:0%"></div>
                </div>
            </div>

            <div class="wi-metrics">
                <div class="wi-metric" title="Net Operating Income ÷ purchase price - your return if you paid 100% cash, no loan"><div class="wi-metric-label">CAP RATE</div><div class="wi-metric-value" id="m-cap">0%</div></div>
                <div class="wi-metric" title="Annual cash flow ÷ total cash invested - your actual ROI on the cash you put in"><div class="wi-metric-label">CASH-ON-CASH ROI</div><div class="wi-metric-value" id="m-coc">0%</div></div>
                <div class="wi-metric" title="Down payment + closing costs - total upfront cash to close this deal"><div class="wi-metric-label">CASH NEEDED</div><div class="wi-metric-value" id="m-cash">$0</div></div>
                <div class="wi-metric" title="Taxes + insurance + management + maintenance + HOA, per month"><div class="wi-metric-label">MONTHLY EXPENSES</div><div class="wi-metric-value" id="m-exp">$0</div></div>
                <div class="wi-metric" title="Rental income minus operating expenses, before the mortgage - your annual operating profit"><div class="wi-metric-label">ANNUAL NOI</div><div class="wi-metric-value" id="m-noi">$0</div></div>
                <div class="wi-metric" title="Debt Service Coverage Ratio: NOI ÷ annual mortgage payment. Lenders typically require 1.20-1.25+ to approve a loan"><div class="wi-metric-label">DSCR</div><div class="wi-metric-value" id="m-dscr">0.00</div></div>
                <div class="wi-metric" title="Gross Rent Multiplier: price ÷ annual gross rent. A quick screening ratio - lower generally means a better deal, typically compared within a local market"><div class="wi-metric-label">GRM</div><div class="wi-metric-value" id="m-grm">0.0</div></div>
                <div class="wi-metric" title="Operating Expense Ratio: total operating expenses ÷ effective gross income. Lower means more of your rent turns into profit"><div class="wi-metric-label">OPEX RATIO</div><div class="wi-metric-value" id="m-oer">0%</div></div>
            </div>
            <div class="wi-metrics-caption">Hover any metric for its definition</div>
        </div>
    </div>
    </div>

    <script>
    (function() {{
        const ids = ['price','down','interest','term','rent','vacancy','mgmt','maint','hoa','closing','target'];
        const el = {{}};
        ids.forEach(id => el[id] = document.getElementById(id));

        let priceBeforeApply = null;
        let settingPriceProgrammatically = false;

        function fmtMoney(n) {{ return '$' + Math.round(n).toLocaleString('en-US'); }}
        function fmtPct(n) {{ return n.toFixed(2) + '%'; }}

        function compute() {{
            const price = parseFloat(el.price.value) || 0;
            const downPct = parseFloat(el.down.value) || 0;
            const interest = parseFloat(el.interest.value) || 0;
            const term = parseFloat(el.term.value) || 30;
            const rent = parseFloat(el.rent.value) || 0;
            const vacancy = parseFloat(el.vacancy.value) || 0;
            const mgmtPct = parseFloat(el.mgmt.value) || 0;
            const maintPct = parseFloat(el.maint.value) || 0;
            const hoa = parseFloat(el.hoa.value) || 0;
            const closing = parseFloat(el.closing.value) || 0;
            const target = parseFloat(el.target.value) || 0;

            const vLoss = (rent*12)*(vacancy/100);
            const effGross = (rent*12)-vLoss;
            const taxes = price*({tax_rate}/100);
            const insurance = price*({ins_rate}/100);
            const mgmtFee = effGross*(mgmtPct/100);
            const maintenance = effGross*(maintPct/100);
            const hoaAnnual = hoa*12;
            const totalExpenses = taxes+insurance+mgmtFee+maintenance+hoaAnnual;
            const noi = Math.max(0, effGross-totalExpenses);
            const capRate = price>0 ? (noi/price)*100 : 0;

            const downAmt = price*(downPct/100);
            const loanAmt = price-downAmt;
            let aDebt = 0;
            if (loanAmt>0 && interest>0) {{
                const mRate = (interest/100)/12;
                const pCount = term*12;
                const mDebt = loanAmt*(mRate*Math.pow(1+mRate,pCount))/(Math.pow(1+mRate,pCount)-1);
                aDebt = mDebt*12;
            }}
            const cashflow = noi-aDebt;
            const totalCash = downAmt+closing;
            const coc = totalCash>0 ? (cashflow/totalCash)*100 : 0;

            let grade = 'average';
            if (cashflow<0) grade = 'critical';
            else if (coc>=target) grade = 'excellent';

            // Update readouts
            el_v('v-price', fmtMoney(price)); el_v('v-down', downPct+'%'); el_v('v-interest', interest.toFixed(3)+'%');
            el_v('v-rent', fmtMoney(rent)); el_v('v-vacancy', vacancy+'%');
            el_v('v-mgmt', mgmtPct+'%'); el_v('v-maint', maintPct+'%'); el_v('v-hoa', fmtMoney(hoa)+'/mo');
            el_v('v-closing', fmtMoney(closing)); el_v('v-target', target+'%');

            const cfMonthly = cashflow/12;
            const cfEl = document.getElementById('cf-value');
            cfEl.textContent = (cfMonthly>=0?'':'-') + fmtMoney(Math.abs(cfMonthly));
            cfEl.style.color = cfMonthly>=0 ? 'var(--green)' : 'var(--red)';

            const colors = {{critical: ['#3f1d1d','#f87171'], average: ['#3f3319','#fbbf24'], excellent: ['#0f3d2e','#10b981']}};
            const labels = {{critical: '🔴 NEGATIVE CASH FLOW', average: '🟡 AVERAGE DEAL', excellent: '🟢 OUTSTANDING DEAL'}};
            const badge = document.getElementById('badge');
            badge.textContent = labels[grade];
            badge.style.background = colors[grade][0];
            badge.style.color = colors[grade][1];

            const gaugeMax = Math.max(25, Math.ceil(coc/5)*5+5, Math.ceil(target/5)*5+5);
            document.getElementById('gauge-max').textContent = gaugeMax+'%';
            const fillPct = Math.max(0, Math.min(100, (coc/gaugeMax)*100));
            const fill = document.getElementById('gauge-fill');
            fill.style.width = fillPct+'%';
            fill.style.background = colors[grade][1];
            document.getElementById('gauge-target').style.left = Math.max(0, Math.min(100, (target/gaugeMax)*100))+'%';

            el_v('m-cap', fmtPct(capRate));
            el_v('m-coc', fmtPct(coc));
            el_v('m-cash', fmtMoney(totalCash));
            el_v('m-exp', fmtMoney(totalExpenses/12));
            el_v('m-noi', fmtMoney(noi));
            const dscr = aDebt > 0 ? (noi/aDebt) : null;
            el_v('m-dscr', dscr === null ? '∞' : dscr.toFixed(2));
            const grossAnnualRent = rent*12;
            const grm = grossAnnualRent > 0 ? (price/grossAnnualRent) : 0;
            el_v('m-grm', grm.toFixed(1));
            const oer = effGross > 0 ? (totalExpenses/effGross)*100 : 0;
            el_v('m-oer', fmtPct(oer));

            // Suggested Max Offer: solve for the price P where Cash-on-Cash ROI
            // exactly equals your target, holding rent/vacancy/mgmt/maintenance/
            // HOA/closing/financing-% assumptions fixed. Derived algebraically
            // rather than searched, so it's exact, not an approximation.
            const fixedNonPriceExpenses = mgmtFee + maintenance + hoaAnnual;
            const A = effGross - fixedNonPriceExpenses;
            const B = ({tax_rate}/100) + ({ins_rate}/100);
            let debtFactor = 0;
            if (interest > 0) {{
                const mRate = (interest/100)/12;
                const pCount = term*12;
                debtFactor = 12 * (mRate*Math.pow(1+mRate,pCount)) / (Math.pow(1+mRate,pCount)-1);
            }}
            const C = (1 - downPct/100) * debtFactor;
            const D = downPct/100;
            const targetFrac = target/100;
            const denom = B + C + (targetFrac * D);
            const numerator = A - (targetFrac * closing);
            const maoBox = document.getElementById('mao-value');
            const maoDelta = document.getElementById('mao-delta');
            const maoApply = document.getElementById('mao-apply');

            if (denom > 0 && numerator > 0) {{
                const suggestedPrice = numerator / denom;
                maoBox.textContent = fmtMoney(suggestedPrice);
                const delta = price - suggestedPrice;
                if (delta > 500) {{
                    maoDelta.textContent = 'That\\'s ' + fmtMoney(delta) + ' lower than your current offer';
                    maoDelta.style.color = 'var(--amber)';
                }} else if (delta < -500) {{
                    maoDelta.textContent = 'Your current offer already clears your target by ' + fmtMoney(-delta);
                    maoDelta.style.color = 'var(--green)';
                }} else {{
                    maoDelta.textContent = 'Your current offer is right at this number';
                    maoDelta.style.color = 'var(--text-dim)';
                }}

                if (priceBeforeApply !== null) {{
                    maoApply.textContent = '↩ Undo (restore ' + fmtMoney(priceBeforeApply) + ')';
                    maoApply.style.display = 'inline-block';
                    maoApply.dataset.mode = 'undo';
                }} else if (delta > 500) {{
                    maoApply.textContent = 'Apply this price';
                    maoApply.style.display = 'inline-block';
                    maoApply.dataset.mode = 'apply';
                    maoApply.dataset.price = Math.round(suggestedPrice);
                }} else {{
                    maoApply.style.display = 'none';
                }}
            }} else {{
                maoBox.textContent = 'Not achievable';
                maoDelta.textContent = 'Your expenses/financing terms are too high to hit this target at any price - try lowering costs or your target return';
                maoDelta.style.color = 'var(--red)';
                if (priceBeforeApply !== null) {{
                    maoApply.textContent = '↩ Undo (restore ' + fmtMoney(priceBeforeApply) + ')';
                    maoApply.style.display = 'inline-block';
                    maoApply.dataset.mode = 'undo';
                }} else {{
                    maoApply.style.display = 'none';
                }}
            }}
        }}

        function el_v(id, text) {{ document.getElementById(id).textContent = text; }}

        el.price.addEventListener('input', function() {{
            if (!settingPriceProgrammatically) {{
                priceBeforeApply = null;
            }}
        }});

        document.getElementById('mao-apply').addEventListener('click', function() {{
            settingPriceProgrammatically = true;
            if (this.dataset.mode === 'undo') {{
                el.price.value = priceBeforeApply;
                priceBeforeApply = null;
            }} else {{
                priceBeforeApply = parseFloat(el.price.value) || 0;
                el.price.value = this.dataset.price;
            }}
            settingPriceProgrammatically = false;
            compute();
            sendHeight();
        }});

        ids.forEach(id => {{
            el[id].addEventListener('input', () => {{ compute(); sendHeight(); }});
            el[id].addEventListener('change', () => {{ compute(); sendHeight(); }});
        }});

        function sendHeight() {{
            const height = document.documentElement.scrollHeight;
            window.parent.postMessage({{type: 'streamlit:setFrameHeight', height: height}}, '*');
        }}

        compute();
        sendHeight();
        window.addEventListener('resize', sendHeight);
        // Re-check shortly after load too, in case web fonts finish loading and reflow the layout
        setTimeout(sendHeight, 300);
        setTimeout(sendHeight, 1000);
    }})();
    </script>

    """
    return html


