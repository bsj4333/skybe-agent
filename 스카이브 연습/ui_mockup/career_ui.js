// Account-wide career knowledge with a separate conversation for each posting.
export function initCareerUI({main, request, showAnalysis, fail, notice}) {
  const section = document.createElement('section');
  section.id = 'career-section';
  section.hidden = true;
  section.innerHTML = `
    <h1 class="workspace-title">자소서 작업 공간</h1>
    <p class="workspace-note">공고별 대화는 따로 저장됩니다. 같은 계정의 드라이브 자료, 본인 진술, 이전 자소서는 필요할 때 함께 찾아봅니다.</p>
    <div class="career-grid">
      <aside class="career-rail">
        <button id="career-new-toggle" class="workspace-action">＋ 공고 만들기</button>
        <form id="career-new-form" hidden>
          <label>공고 이름<input id="career-title" required maxlength="200" placeholder="예: 기아 생산기술"></label>
          <label>공고 URL · 참고 링크<input id="career-url" type="url" placeholder="https://..."></label>
          <label>인재상 URL · 참고 링크<input id="career-values-url" type="url" placeholder="https://..."></label>
          <label>공고 내용 · 현재 직접 붙여넣기<textarea id="career-job-text" placeholder="URL 본문 자동 읽기는 준비 중입니다. 직무·요구사항을 붙여 넣으세요."></textarea></label>
          <label>자소서 문항<textarea id="career-questions" placeholder="한 줄에 문항 하나씩 입력하세요"></textarea></label>
          <button type="submit" class="workspace-action">공고 저장</button>
        </form>
        <h2>내 공고</h2><div id="career-jobs"></div>
      </aside>
      <div class="career-body">
        <div id="career-empty" class="workspace-card">공고를 만들거나 왼쪽에서 선택하세요.</div>
        <div id="career-detail" hidden>
          <div class="career-heading"><div><h2 id="career-job-title"></h2><a id="career-job-link" target="_blank" rel="noopener noreferrer" hidden>공고 원문 ↗</a></div><span id="career-job-date" class="muted"></span></div>
          <p class="career-rule">파일 근거 · 본인 진술 · 이전 자소서 표현을 구분합니다. 원본에 없거나 내용이 충돌하면 먼저 확인 질문을 합니다.</p>
          <label class="career-question-label">작성할 문항 <select id="career-question-select"><option value="">일반 대화</option></select></label>
          <div class="career-columns">
            <div class="career-draft-pane"><h3>현재 초안 <small>검토 필요</small></h3><div id="career-draft" class="essay-draft"></div><div id="career-draft-sources" class="citation-list"></div><button id="career-versions" class="small">이전 버전 보기</button><div id="career-version-list" hidden></div></div>
            <div class="career-chat-pane"><h3>이 공고에서 AI와 대화</h3><div id="career-messages" class="career-messages"></div>
              <div id="career-pending" class="career-pending" hidden></div>
              <textarea id="career-message-input" placeholder="예: 전에 쓴 자소서 표현 참고해서 이 문항 초안 써줘"></textarea>
              <div class="career-send-actions"><button id="career-send" class="workspace-action">보내기</button><button id="career-answer" class="workspace-action" hidden>질문에 답변으로 저장</button></div>
            </div>
          </div>
        </div>
      </div>
    </div>`;
  main.append(section);
  const style = document.createElement('style');
  style.textContent = `
    .career-grid{display:grid;grid-template-columns:245px minmax(0,1fr);gap:22px}
    .career-rail{width:100%;padding:14px;border:1px solid #e2e8e7;border-radius:14px;align-self:start;background:#fff}
    .career-rail h2{font-size:15px;margin:22px 0 10px}.career-rail label{display:block;font-size:12px;margin:10px 0;color:#5f6368}
    .career-rail input,.career-rail textarea,.career-question-label select,.career-chat-pane textarea{display:block;width:100%;padding:9px;border:1px solid #cbd5da;border-radius:8px;font:inherit;color:#202124;background:#fff}
    .career-rail textarea{min-height:80px}.career-rail button{width:100%}.career-rail #career-jobs button{width:100%;text-align:left;border:0;background:transparent;border-radius:8px;padding:10px}
    .career-rail #career-jobs button:hover,.career-rail #career-jobs button.active{background:#e4f1ef}
    .career-heading{display:flex;justify-content:space-between;gap:15px;align-items:start}.career-heading h2{margin:0 0 5px}.career-heading a{font-size:13px;color:#26736d}
    .career-rule{padding:10px 14px;background:#eef5f4;border-radius:8px;color:#385753;font-size:13px}
    .career-question-label{display:block;margin:18px 0;font-weight:600}.career-question-label select{margin-top:7px;max-width:680px;font-weight:400}
    .career-columns{display:grid;grid-template-columns:minmax(0,1fr) minmax(320px,.9fr);gap:16px}.career-draft-pane,.career-chat-pane{border:1px solid #e2e8e7;border-radius:13px;padding:17px;background:white;min-height:520px}
    .career-draft-pane h3,.career-chat-pane h3{margin:0 0 12px;font-size:17px}.career-draft-pane small{font-weight:400;color:#7b5b34}
    .career-messages{height:330px;overflow-y:auto;display:flex;flex-direction:column;gap:10px;margin-bottom:12px}.career-message{border-radius:11px;padding:10px 12px;white-space:pre-wrap;line-height:1.55;background:#f0f3f5;font-size:14px}
    .career-message.user{background:#d7eae6;align-self:flex-end}.career-ref{font-size:12px;color:#5f6368}.career-ref button{border:0;background:transparent;color:#26736d;text-decoration:underline;display:block;text-align:left;margin:4px 0}
    .career-chat-pane textarea{min-height:75px;resize:vertical}.career-send-actions{display:flex;gap:8px;flex-wrap:wrap}.career-pending{padding:10px;background:#fff5df;border-radius:8px;margin-bottom:10px;font-size:13px}
    @media(max-width:1050px){.career-grid,.career-columns{grid-template-columns:1fr}.career-rail{width:auto}}
  `;
  document.head.append(style);
  const el = id => section.querySelector('#' + id);
  let activeJob = null;
  let jobData = null;
  let busy = false;

  function addReference(container, references) {
    container.replaceChildren();
    for (const source of references?.files || references || []) {
      const button = document.createElement('button');
      button.textContent = `[파일 ${source.index}] ${source.name} · ${source.location}`;
      button.onclick = () => showAnalysis({id:source.file_id,upload_status:'uploaded'}).catch(fail);
      container.append(button);
    }
    for (const fact of references?.activity_facts || []) {
      const button = document.createElement('button');
      button.textContent = `[활동 사실 ${fact.index}] ${fact.activity_title} · ${fact.file_name} · ${fact.location}`;
      button.onclick = () => showAnalysis({id:fact.file_id,upload_status:'uploaded'}).catch(fail);
      container.append(button);
    }
    if (references?.user_statements?.length) {
      const label = document.createElement('div');
      label.textContent = `본인 진술 ${references.user_statements.length}건 참고 · 파일 근거와 구분`;
      container.append(label);
    }
    if (references?.past_essays?.length) {
      const label = document.createElement('div');
      label.textContent = `이전 자소서 ${references.past_essays.length}건 표현 참고 · 사실 근거 아님`;
      container.append(label);
    }
  }
  function renderMessages(messages) {
    const log = el('career-messages'); log.replaceChildren();
    for (const message of messages) {
      const row = document.createElement('div'); row.className = 'career-message ' + message.role; row.textContent = message.content; log.append(row);
      if (message.role === 'assistant' && message.references_json) {
        const refs = document.createElement('div'); refs.className = 'career-ref'; addReference(refs, message.references_json); log.append(refs);
      }
    }
    log.scrollTop = log.scrollHeight;
  }
  function renderEssay() {
    const selected = jobData?.essays.find(item => item.id === el('career-question-select').value);
    el('career-draft').textContent = selected?.draft || '문항을 선택하고 AI와 대화하며 초안을 작성하세요.';
    addReference(el('career-draft-sources'), selected?.citations || []);
    el('career-version-list').hidden = true;
  }
  async function loadJobs() {
    const jobs = await request('/jobs');
    const list = el('career-jobs'); list.replaceChildren();
    for (const job of jobs) {
      const button = document.createElement('button');
      button.textContent = `${job.title} · ${job.question_count}문항`;
      button.className = job.id === activeJob ? 'active' : '';
      button.onclick = () => openJob(job.id).catch(fail);
      list.append(button);
    }
  }
  async function openJob(id) {
    jobData = await request('/jobs/' + id); activeJob = id;
    el('career-empty').hidden = true; el('career-detail').hidden = false;
    el('career-job-title').textContent = jobData.title;
    el('career-job-date').textContent = new Date(jobData.created_at).toLocaleDateString('ko-KR');
    const link = el('career-job-link'); link.hidden = !jobData.job_url; if (jobData.job_url) link.href = jobData.job_url;
    const select = el('career-question-select'); const selected = select.value; select.replaceChildren(new Option('일반 대화', ''));
    for (const essay of jobData.essays) select.add(new Option(essay.question, essay.id));
    select.value = jobData.essays.some(item => item.id === selected) ? selected : (jobData.essays[0]?.id || '');
    renderEssay(); renderMessages(jobData.messages);
    el('career-pending').hidden = !jobData.pending_question;
    el('career-pending').textContent = jobData.pending_question ? `AI 확인 질문: ${jobData.pending_question}` : '';
    el('career-answer').hidden = !jobData.pending_question;
    await loadJobs();
  }
  async function send(answerPending = false) {
    if (!activeJob || busy) return;
    const text = el('career-message-input').value.trim(); if (!text) return;
    busy = true; el('career-send').disabled = el('career-answer').disabled = true;
    try {
      const essayId = el('career-question-select').value || null;
      const result = await request(`/jobs/${activeJob}/messages`, {method:'POST',body:JSON.stringify({message:text,essay_id:essayId,answer_pending:answerPending})});
      el('career-message-input').value = '';
      await openJob(activeJob);
      if (result.action === 'ask') notice('AI가 확인 질문을 남겼습니다. 답변은 본인 진술로 저장할 수 있어요.');
      if (result.action === 'draft') notice('초안을 저장했습니다. 문장과 출처를 검토해 주세요.');
    } catch (error) { fail(error); } finally { busy = false; el('career-send').disabled = el('career-answer').disabled = false; }
  }
  el('career-new-toggle').onclick = () => { el('career-new-form').hidden = !el('career-new-form').hidden; };
  el('career-new-form').onsubmit = async event => {
    event.preventDefault();
    try {
      const payload = {title:el('career-title').value.trim(),job_url:el('career-url').value.trim(),values_url:el('career-values-url').value.trim(),job_text:el('career-job-text').value.trim(),questions:el('career-questions').value.split('\n').map(value=>value.trim()).filter(Boolean)};
      const job = await request('/jobs',{method:'POST',body:JSON.stringify(payload)});
      el('career-new-form').reset(); el('career-new-form').hidden = true; await openJob(job.id);
      notice('공고별 작업 공간을 만들었습니다.');
    } catch (error) { fail(error); }
  };
  el('career-question-select').onchange = renderEssay;
  el('career-versions').onclick = async () => {
    const essayId = el('career-question-select').value;
    if (!essayId) return;
    const list = el('career-version-list');
    if (!list.hidden) { list.hidden = true; return; }
    try {
      const versions = await request(`/jobs/${activeJob}/essays/${essayId}/versions`);
      list.replaceChildren();
      if (!versions.length) list.textContent = '아직 저장된 초안 버전이 없습니다.';
      for (const version of versions) {
        const button = document.createElement('button'); button.className = 'small';
        button.textContent = `버전 ${version.revision_no} · ${new Date(version.created_at).toLocaleString('ko-KR')}`;
        button.onclick = () => {el('career-draft').textContent = version.draft; addReference(el('career-draft-sources'), version.citations);};
        list.append(button);
      }
      list.hidden = false;
    } catch (error) {fail(error);}
  };
  el('career-send').onclick = () => send(false);
  el('career-answer').onclick = () => send(true);
  el('career-message-input').onkeydown = event => {if(event.key === 'Enter' && !event.shiftKey){event.preventDefault();send(false)}};
  return {section, show:loadJobs};
}
