let cachedState = null;

        function escapeHtml(str) {
            if (str === null || str === undefined) return '';
            return String(str)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#039;');
        }

        function sanitizeUrl(url) {
            if (!url || typeof url !== 'string') return '#';
            const trimmed = url.trim();
            if (/^(?:javascript|data|vbscript|file):/i.test(trimmed)) {
                return '#';
            }
            let candidate = trimmed;
            if (!/^https?:\/\//i.test(candidate)) {
                if (/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(candidate)) {
                    return '#';
                }
                candidate = 'https://' + candidate;
            }
            try {
                const parsed = new URL(candidate);
                if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
                    return parsed.href;
                }
            } catch (e) {
                return '#';
            }
            return '#';
        }

        function renderHistoryChart(history) {
            const container = document.getElementById('history-chart-container');
            if (!container) return;
            while (container.firstChild) {
                container.removeChild(container.firstChild);
            }
            if (!history || history.length === 0) {
                const empty = document.createElement('div');
                empty.className = 'text-xs text-slate-500 m-auto font-sans';
                empty.textContent = 'No sync cycles recorded yet.';
                container.appendChild(empty);
                return;
            }

            const items = [...history].reverse();
            let maxDuration = 1.0;
            items.forEach(item => {
                if (item.duration_ms && item.duration_ms > maxDuration) {
                    maxDuration = item.duration_ms;
                }
            });

            items.forEach(item => {
                const barWrapper = document.createElement('div');
                barWrapper.className = 'flex-1 flex flex-col items-center justify-end h-full min-w-[12px] group relative cursor-pointer';

                const duration = item.duration_ms || 0.0;
                const pct = Math.max(8, Math.min(100, Math.round((duration / maxDuration) * 100)));

                const bar = document.createElement('div');
                bar.style.height = pct + '%';
                bar.className = 'w-full rounded-t transition-all ';

                const st = (item.status || '').toLowerCase();
                if (st.includes('active') || st.includes('synced') || st === 'success') {
                    bar.className += 'bg-emerald-500 group-hover:bg-emerald-400';
                } else if (st.includes('degraded') || st.includes('warning')) {
                    bar.className += 'bg-amber-500 group-hover:bg-amber-400';
                } else {
                    bar.className += 'bg-rose-500 group-hover:bg-rose-400';
                }

                const timeStr = item.iso_time ? item.iso_time.split('T')[1].substring(0, 8) : '';
                barWrapper.title = `${timeStr} UTC · ${duration.toFixed(1)}ms · ${item.status || 'unknown'} (${item.services_count || 0} origins)`;

                barWrapper.appendChild(bar);
                container.appendChild(barWrapper);
            });
        }

        function renderEventsTimeline() {
            const container = document.getElementById('events-timeline-container');
            if (!container || !cachedState) return;

            const searchInput = document.getElementById('event-search-input');
            const q = searchInput ? searchInput.value.trim().toLowerCase() : '';

            const severitySelect = document.getElementById('event-severity-select');
            const filterSeverity = severitySelect ? severitySelect.value.trim().toLowerCase() : '';

            let events = cachedState.events || [];

            if (events.length === 0 && cachedState.logs && cachedState.logs.length > 0) {
                while (container.firstChild) {
                    container.removeChild(container.firstChild);
                }
                cachedState.logs.forEach(log => {
                    if (q && !log.toLowerCase().includes(q)) return;
                    const div = document.createElement('div');
                    div.className = 'text-slate-300';
                    div.textContent = log;
                    container.appendChild(div);
                });
                return;
            }

            if (filterSeverity) {
                events = events.filter(e => (e.severity || '').toLowerCase() === filterSeverity);
            }
            if (q) {
                events = events.filter(e => {
                    const msg = (e.message || '').toLowerCase();
                    const svc = (e.service || '').toLowerCase();
                    const typ = (e.event_type || '').toLowerCase();
                    return msg.includes(q) || svc.includes(q) || typ.includes(q);
                });
            }

            while (container.firstChild) {
                container.removeChild(container.firstChild);
            }

            if (events.length === 0) {
                const empty = document.createElement('div');
                empty.className = 'text-xs text-slate-500 py-4 text-center font-sans';
                empty.textContent = 'No matching audit events found.';
                container.appendChild(empty);
                return;
            }

            events.forEach(evt => {
                const row = document.createElement('div');
                row.className = 'p-2 rounded bg-slate-900/60 border border-slate-800 flex items-start gap-3 hover:bg-slate-900';

                const sevBadge = document.createElement('span');
                const sev = (evt.severity || 'info').toLowerCase();
                if (sev === 'error') {
                    sevBadge.className = 'px-1.5 py-0.5 rounded text-[10px] font-bold uppercase bg-rose-500/20 text-rose-400 border border-rose-500/30';
                    sevBadge.textContent = 'ERR';
                } else if (sev === 'warning' || sev === 'warn') {
                    sevBadge.className = 'px-1.5 py-0.5 rounded text-[10px] font-bold uppercase bg-amber-500/20 text-amber-400 border border-amber-500/30';
                    sevBadge.textContent = 'WARN';
                } else {
                    sevBadge.className = 'px-1.5 py-0.5 rounded text-[10px] font-bold uppercase bg-sky-500/20 text-sky-400 border border-sky-500/30';
                    sevBadge.textContent = 'INFO';
                }
                row.appendChild(sevBadge);

                const contentWrapper = document.createElement('div');
                contentWrapper.className = 'flex-1 min-w-0';

                const topMeta = document.createElement('div');
                topMeta.className = 'flex items-center gap-2 text-[11px] text-slate-400';

                const typeSpan = document.createElement('span');
                typeSpan.className = 'font-semibold text-slate-200';
                typeSpan.textContent = evt.event_type || 'SYNC';
                topMeta.appendChild(typeSpan);

                if (evt.service && evt.service !== '-') {
                    const svcSpan = document.createElement('span');
                    svcSpan.className = 'text-orange-400/90';
                    svcSpan.textContent = `[${evt.service}]`;
                    topMeta.appendChild(svcSpan);
                }

                const timeSpan = document.createElement('span');
                timeSpan.className = 'text-slate-500 ml-auto font-mono text-[10px]';
                timeSpan.textContent = evt.iso_time ? evt.iso_time.replace('T', ' ').substring(0, 19) + ' UTC' : '';
                topMeta.appendChild(timeSpan);

                contentWrapper.appendChild(topMeta);

                const msgDiv = document.createElement('div');
                msgDiv.className = 'text-slate-300 text-xs mt-0.5 break-words';
                msgDiv.textContent = evt.message || '';
                contentWrapper.appendChild(msgDiv);

                row.appendChild(contentWrapper);
                container.appendChild(row);
            });
        }

        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                if (res.status === 401) {
                    window.location.reload();
                    return;
                }
                const data = await res.json();
                cachedState = data;

                // 1. Header Badges
                const statusBadge = document.getElementById('status-badge');
                if (statusBadge) {
                    statusBadge.textContent = data.status || 'Initializing...';
                    if (data.status && (data.status.includes('Active') || data.status.includes('Synced'))) {
                        statusBadge.className = 'px-3 py-1 text-xs font-semibold rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30';
                    } else if (data.status && data.status.includes('Error')) {
                        statusBadge.className = 'px-3 py-1 text-xs font-semibold rounded-full bg-rose-500/20 text-rose-400 border border-rose-500/30';
                    } else {
                        statusBadge.className = 'px-3 py-1 text-xs font-semibold rounded-full bg-amber-500/20 text-amber-400 border border-amber-500/30';
                    }
                }

                const webhookBadge = document.getElementById('webhook-badge');
                if (webhookBadge && data.alert_status) {
                    while (webhookBadge.firstChild) {
                        webhookBadge.removeChild(webhookBadge.firstChild);
                    }
                    const ast = data.alert_status;
                    const dot = document.createElement('span');
                    dot.className = 'w-2 h-2 rounded-full';
                    if (ast.configured) {
                        const prov = (ast.provider || 'webhook').toUpperCase();
                        if (ast.cooldown_active) {
                            webhookBadge.className = 'px-3 py-1 text-xs font-semibold rounded-full bg-amber-500/20 text-amber-400 border border-amber-500/30 flex items-center gap-1.5';
                            dot.className += ' bg-amber-400 animate-pulse';
                            webhookBadge.appendChild(dot);
                            webhookBadge.appendChild(document.createTextNode(` Alerts: ${prov} (Cooldown)`));
                        } else {
                            webhookBadge.className = 'px-3 py-1 text-xs font-semibold rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 flex items-center gap-1.5';
                            dot.className += ' bg-emerald-400';
                            webhookBadge.appendChild(dot);
                            webhookBadge.appendChild(document.createTextNode(` Alerts: ${prov} (Active)`));
                        }
                    } else {
                        webhookBadge.className = 'px-3 py-1 text-xs font-semibold rounded-full bg-slate-800 text-slate-400 border border-slate-700 flex items-center gap-1.5';
                        dot.className += ' bg-slate-500';
                        webhookBadge.appendChild(dot);
                        webhookBadge.appendChild(document.createTextNode(' Alerts: None'));
                    }
                }

                // 2. Overview Cards 
                const overview = data.overview_metrics || {};
                const healthText = document.getElementById('health-state-text');
                const healthIcon = document.getElementById('health-icon');
                if (healthText && healthIcon) {
                    const hs = overview.health_state || 'unknown';
                    if (hs === 'healthy') {
                        healthText.textContent = 'Healthy';
                        healthText.className = 'text-2xl font-extrabold text-emerald-400 mt-2';
                        healthIcon.textContent = '✅';
                    } else if (hs === 'never_synced') {
                        healthText.textContent = 'Never Synced';
                        healthText.className = 'text-2xl font-extrabold text-slate-400 mt-2';
                        healthIcon.textContent = '⏳';
                    } else if (hs === 'degraded') {
                        healthText.textContent = 'Degraded';
                        healthText.className = 'text-2xl font-extrabold text-amber-400 mt-2';
                        healthIcon.textContent = '⚠️';
                    } else {
                        healthText.textContent = hs.toUpperCase();
                        healthText.className = 'text-2xl font-extrabold text-rose-400 mt-2';
                        healthIcon.textContent = '❌';
                    }
                }

                const safetyStatus = document.getElementById('safety-guard-status');
                if (safetyStatus) {
                    if (data.safety_guard_tripped) {
                        safetyStatus.textContent = '⚠️ Safeguard: BLAST LIMIT TRIPPED';
                        safetyStatus.className = 'font-mono text-rose-400 font-bold';
                    } else {
                        safetyStatus.textContent = 'Safeguards: Normal';
                        safetyStatus.className = 'font-mono text-emerald-400';
                    }
                }

                const svcSummary = document.getElementById('services-summary');
                const svcBreakdown = document.getElementById('services-breakdown');
                if (svcSummary && svcBreakdown) {
                    const act = overview.active_services || 0;
                    const disc = overview.discovered_services || 0;
                    const fail = overview.failed_services || 0;
                    svcSummary.textContent = `${act} Active`;
                    svcBreakdown.textContent = `${disc} discovered · ${fail} failed`;
                }

                const syncDur = document.getElementById('sync-duration-text');
                const lastSyncEl = document.getElementById('last-sync');
                if (syncDur) {
                    const ms = overview.last_sync_duration_ms || 0.0;
                    syncDur.textContent = `Duration: ${ms.toFixed(1)} ms`;
                }
                if (lastSyncEl) {
                    lastSyncEl.textContent = data.last_sync || 'Never';
                }

                const elTunnelName = document.getElementById('tunnel-name');
                if (elTunnelName) elTunnelName.textContent = data.tunnel_name || '-';

                const elTunnelId = document.getElementById('tunnel-id');
                if (elTunnelId) elTunnelId.textContent = data.tunnel_id ? "ID: " + data.tunnel_id.substring(0, 18) + "..." : 'ID: -';

                const elDomainName = document.getElementById('domain-name');
                if (elDomainName) elDomainName.textContent = data.domain_name || '-';

                // 3. Render Sync History Sparkline Chart 
                renderHistoryChart(data.sync_history || []);

                // 4. Render Discovered Containers Table & Diagnostics 
                const tbody = document.getElementById('hosts-tbody');
                if (tbody) {
                    while (tbody.firstChild) {
                        tbody.removeChild(tbody.firstChild);
                    }

                    if (data.all_containers && data.all_containers.length > 0) {
                        data.all_containers.forEach(c => {
                            const tr = document.createElement('tr');
                            tr.className = 'hover:bg-slate-800/50';

                            // Container Name
                            const tdName = document.createElement('td');
                            tdName.className = 'px-4 py-3 font-sans font-medium text-slate-200';
                            tdName.textContent = c.name != null ? c.name : '-';
                            tr.appendChild(tdName);

                            // Container Image
                            const tdImage = document.createElement('td');
                            tdImage.className = 'px-4 py-3 text-slate-400 text-xs';
                            tdImage.textContent = c.image != null ? c.image : '-';
                            tr.appendChild(tdImage);

                            // Container Status
                            const tdStatus = document.createElement('td');
                            tdStatus.className = 'px-4 py-3';
                            const badgeSpan = document.createElement('span');
                            if (c.state === 'running') {
                                badgeSpan.className = 'px-2 py-0.5 text-xs rounded bg-emerald-950 text-emerald-400 border border-emerald-800';
                                badgeSpan.textContent = 'Running';
                            } else {
                                badgeSpan.className = 'px-2 py-0.5 text-xs rounded bg-rose-950 text-rose-400 border border-rose-800';
                                badgeSpan.textContent = c.state || 'Unknown';
                            }
                            tdStatus.appendChild(badgeSpan);
                            tr.appendChild(tdStatus);

                            // Tunnel Hostname
                            const tdTunnel = document.createElement('td');
                            tdTunnel.className = 'px-4 py-3 font-mono text-xs';

                            // DNS Status
                            const tdDns = document.createElement('td');
                            tdDns.className = 'px-4 py-3';

                            const rawHost = c.hostname && c.hostname !== '-' ? String(c.hostname).trim() : null;

                            if (c.is_tunneled && rawHost) {
                                const safeUrl = sanitizeUrl(rawHost);
                                if (safeUrl !== '#') {
                                    const link = document.createElement('a');
                                    link.href = safeUrl;
                                    link.target = '_blank';
                                    link.rel = 'noopener noreferrer';
                                    link.className = 'text-orange-400 hover:underline flex items-center gap-1.5 font-semibold';
                                    link.textContent = rawHost;

                                    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
                                    svg.setAttribute('class', 'w-3.5 h-3.5 opacity-60');
                                    svg.setAttribute('fill', 'none');
                                    svg.setAttribute('stroke', 'currentColor');
                                    svg.setAttribute('viewBox', '0 0 24 24');
                                    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                                    path.setAttribute('stroke-linecap', 'round');
                                    path.setAttribute('stroke-linejoin', 'round');
                                    path.setAttribute('stroke-width', '2');
                                    path.setAttribute('d', 'M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14');
                                    svg.appendChild(path);
                                    link.appendChild(svg);

                                    tdTunnel.appendChild(link);
                                } else {
                                    const blockedSpan = document.createElement('span');
                                    blockedSpan.className = 'text-amber-400 font-mono';
                                    blockedSpan.textContent = rawHost;
                                    tdTunnel.appendChild(blockedSpan);
                                }

                                const statusWrapper = document.createElement('div');
                                statusWrapper.className = 'flex flex-col gap-1.5';

                                const headerWrapper = document.createElement('div');
                                headerWrapper.className = 'flex items-center gap-2';

                                const dnsSpan = document.createElement('span');
                                const svcStatus = c.status || 'Synced';
                                if (svcStatus === 'Synced') {
                                    dnsSpan.className = 'text-emerald-400 font-semibold';
                                    dnsSpan.textContent = 'Active & Synced';
                                } else if (svcStatus === 'Degraded') {
                                    dnsSpan.className = 'text-amber-400 font-semibold';
                                    dnsSpan.textContent = 'Degraded';
                                } else if (svcStatus === 'Failed') {
                                    dnsSpan.className = 'text-rose-400 font-semibold';
                                    dnsSpan.textContent = 'Failed';
                                } else {
                                    dnsSpan.className = 'text-sky-400 font-semibold';
                                    dnsSpan.textContent = svcStatus;
                                }
                                headerWrapper.appendChild(dnsSpan);
                                statusWrapper.appendChild(headerWrapper);

                                if (c.stages && Object.keys(c.stages).length > 0) {
                                    const stagesDiv = document.createElement('div');
                                    stagesDiv.className = 'flex items-center gap-1 flex-wrap';

                                    const stageLabels = [
                                        { key: 'LABEL_SYNTAX', short: 'SYN' },
                                        { key: 'TUNNEL_DOMAIN_MATCH', short: 'DOM' },
                                        { key: 'NETWORK_TOPOLOGY', short: 'NET' },
                                        { key: 'CLOUDFLARE_INGRESS', short: 'ING' },
                                        { key: 'CLOUDFLARE_DNS', short: 'DNS' },
                                        { key: 'ORIGIN_HEALTH', short: 'HLT' }
                                    ];

                                    let actionableHint = null;

                                    stageLabels.forEach(s => {
                                        const stageData = c.stages[s.key] || { status: 'PENDING', message: '' };
                                        const pill = document.createElement('span');
                                        pill.className = 'px-1.5 py-0.5 rounded text-[10px] font-mono border ';
                                        if (stageData.status === 'PASS') {
                                            pill.className += 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30';
                                        } else if (stageData.status === 'WARNING') {
                                            pill.className += 'bg-amber-500/20 text-amber-300 border-amber-500/30';
                                            if (!actionableHint && stageData.message) {
                                                actionableHint = `[${s.short}] ${stageData.message}`;
                                            }
                                        } else if (stageData.status === 'FAILED') {
                                            pill.className += 'bg-rose-500/20 text-rose-300 border-rose-500/30 font-bold';
                                            if (!actionableHint && stageData.message) {
                                                actionableHint = `[${s.short}] ${stageData.message}`;
                                            }
                                        } else {
                                            pill.className += 'bg-slate-500/20 text-slate-400 border-slate-500/30';
                                        }
                                        pill.textContent = s.short;
                                        pill.title = `${s.key}: ${stageData.status} - ${stageData.message}`;
                                        stagesDiv.appendChild(pill);
                                    });

                                    statusWrapper.appendChild(stagesDiv);

                                    if (actionableHint) {
                                        const hintDiv = document.createElement('div');
                                        hintDiv.className = 'text-[11px] text-amber-400/90 font-sans mt-0.5';
                                        hintDiv.textContent = `💡 Hint: ${actionableHint}`;
                                        statusWrapper.appendChild(hintDiv);
                                    }
                                }

                                tdDns.appendChild(statusWrapper);
                            } else if (rawHost) {
                                const inactiveSpan = document.createElement('span');
                                inactiveSpan.className = 'text-slate-500 line-through';
                                inactiveSpan.textContent = rawHost;
                                tdTunnel.appendChild(inactiveSpan);

                                const dnsSpan = document.createElement('span');
                                dnsSpan.className = 'text-slate-500 font-sans italic text-xs';
                                dnsSpan.textContent = 'Stopped (Inactive)';
                                tdDns.appendChild(dnsSpan);
                            } else {
                                const emptyTunnel = document.createElement('span');
                                emptyTunnel.className = 'text-slate-600 font-sans text-xs italic';
                                emptyTunnel.textContent = '-';
                                tdTunnel.appendChild(emptyTunnel);

                                const emptyDns = document.createElement('span');
                                emptyDns.className = 'text-slate-600 font-sans text-xs italic';
                                emptyDns.textContent = '-';
                                tdDns.appendChild(emptyDns);
                            }

                            tr.appendChild(tdTunnel);
                            tr.appendChild(tdDns);
                            tbody.appendChild(tr);
                        });
                    } else {
                        const emptyTr = document.createElement('tr');
                        const emptyTd = document.createElement('td');
                        emptyTd.colSpan = 5;
                        emptyTd.className = 'px-4 py-6 text-center text-slate-500 font-sans';
                        emptyTd.textContent = 'No containers found.';
                        emptyTr.appendChild(emptyTd);
                        tbody.appendChild(emptyTr);
                    }
                }

                // 5. Render Events Timeline 
                renderEventsTimeline();

            } catch (err) {
                console.error("Fetch status error:", err);
            }
        }

        async function triggerSync() {
            const btn = document.getElementById('sync-btn');
            btn.disabled = true;
            btn.classList.add('opacity-50');
            try {
                await fetch('/api/sync', { method: 'POST' });
                await fetchStatus();
            } finally {
                btn.disabled = false;
                btn.classList.remove('opacity-50');
            }
        }

        document.addEventListener("DOMContentLoaded", () => {
    const syncBtn = document.getElementById("sync-btn");
    if (syncBtn) {
        syncBtn.addEventListener("click", triggerSync);
    }

    const eventSearchInput = document.getElementById("event-search-input");
    if (eventSearchInput) {
        eventSearchInput.addEventListener("input", renderEventsTimeline);
    }

    const eventSeveritySelect = document.getElementById("event-severity-select");
    if (eventSeveritySelect) {
        eventSeveritySelect.addEventListener("change", renderEventsTimeline);
    }
});

setInterval(fetchStatus, 3000);
        fetchStatus();
