# 本仓自治规则（内容层：自停 · 自愈 · 英文泄漏自查）

TOPICS.md 是本仓选题的**唯一真相源**。以下三条每次运行都适用；trigger 的启用/停用由外部 `verify-routine-caps` 守卫按 N_pub vs N_top 统一管，**你不要去改 trigger**。

## 1. 自停（写完 TOPICS 就不再生成）
运行开头先算：
- `N_pub` = 已发布页最高编号：`ls *-day*.html`（或本仓命名 week/issue/book/topic）去 `.en.html`、去前导零取最大。
- `N_top` = TOPICS.md 最大编号：`grep '^[-*#]* *(Day|Week|Issue|Book|Topic) *[0-9]+'` 取最大。

**若 N_pub ≥ N_top（TOPICS 已全部写完）**：本次**不生成任何页面、不修改 TOPICS.md、绝不自己发明新主题**；直接结束（至多发一条『本站已写完 TOPICS 路线图，补充新主题后自动续写』的通知，且仅在你判断这是刚写完的当次时发，不要每次都发）。**这条优先级高于本仓 routine prompt 里任何"超表就自造新主题"的旧措辞。** 新主题只由 BigCat 手动或 deep-research 反哺加进 TOPICS.md；加了之后守卫会自动重开、routine 自然续写。

## 2. 自愈（保持 TOPICS ⊇ 已发布）
**只在越界时动手**：若本期 Day/编号按 TOPICS 计划写、TOPICS 里本就有这行 → 不动。只有当你发布的编号是 **TOPICS.md 里没有的**（用户手动指定主题、或 deep-research 反哺内容，当时漏记进 TOPICS）时：
1. 用本期页面标题/副标题，在 TOPICS.md **末尾 append** 一行 `- Day N: <主题> — <要点>`（前缀 Day/Week/Issue/Book/Topic 随本仓约定，先 `grep` 看已有行照抄）。
2. 与本期内容改动**一并 commit / push 到 main**。
3. **只 append，绝不修改已有行。** 否则越界页占了 `dayN`、TOPICS 缺行，日后往 TOPICS 补的 Day N 新主题会撞车永远写不出。

## 3. 英文页中文泄漏自查
生成 `*.en.html` 后、publish 前，对它 grep 这些指纹（命中=模板槽把中文漏进了英文页）：
`class="en">[一-鿿]` / `class="name-en">[一-鿿]` / `class="name-zh">[一-鿿]` / `class="cn">[一-鿿]` / `Reflections — [一-鿿]` / `class="lang-tag">ZH`
命中就修掉（删中文节点或译成英文）再 publish。**正常情况不算泄漏**：经文/古典原典+英译、孙子兵法原文+英译、term(中文) 括注、代码/分词演示、语言切换标签『中文』、主题本身是中文的页。


## index 维护：roadmap-first（写时把灰色占位转成链接，勿 append 重复）

本仓 `index.html` / `index.en.html` 已改为「路线图先出」：TOPICS.md 里**还没写**的条目，已作为灰色占位行 `<div class="entry todo">…</div>`（无 href、不可点、`todo` 类）预先列在列表里。

**写某编号 N 时**：在**两个** index 里找到该 N 对应的那行灰色占位 `<div class="entry todo">`，**原地改成可点链接**——把 `<div class="entry todo">…</div>` 换成 `<a class="entry" href="{本期文件名}">…</a>`（去掉 `todo` 类、加 href，内部 span 结构保持不变）。`index.html` 用中文页文件名、`index.en.html` 用 `.en.html` 文件名。

**绝不要**在列表末尾另 append 一行——否则会和灰色占位行重复出现两条。

只有当该 N 在 index 里**没有**对应灰色占位行时（越界 / 新反哺主题当时没进占位），才在列表末尾 append 新的 `<a class="entry">` 行。


### 每次运行先「对齐」灰色占位（TOPICS 增长时自动补灰行）

每次运行开头，先扫 `TOPICS.md`：凡是**还没写**（无对应页）**且** index 里**还没有对应行**的编号，就按编号顺序在列表相应位置补一条灰色占位行 `<div class="entry todo">…</div>`（无 href、`todo` 类），内部 span 结构照现有条目。`index.en.html` 里顺带把标题/要点翻成 house-style 英文（**勿泄漏中文**），`index.html` 用 TOPICS 中文文本裁成本仓 zh 风格。**两个 index 都要补。**

这样 BigCat / deep-research 往 TOPICS 末尾加的新主题，下次运行就会自动作为灰色条目出现；等真正写它时再按上面的规则**原地**转成链接（勿另 append）。

## 新页面必带共享脚本（免触发 inject-comments 机器人提交）

生成任何 `*.html`（含 `.en.html`）时，在 `</body>` 前直接写入这 4 行，勿遗漏：

```html
<script src="https://hub.cissychen.com/comments.js" defer></script>
<script src="https://hub.cissychen.com/search.js" defer></script>
<script src="https://hub.cissychen.com/index-button.js" defer></script>
<script src="https://hub.cissychen.com/i18n-tts.js" defer></script>
```

这样 CI 的 inject-comments 不会再对新页面追加自动提交。

## 页面结构增补：越界 + 十条要点（2026-10-17 起）

每期中文页和英文页都加两节，**放在最后一张原则卡 `</section>` 之后、收尾节之前**（收尾节＝「深入思考」`section.deep` / `.deep-title`、「把 X 收成一句话」`section.closing`，以及 `.nav`）。顺序：越界在前，十条要点在后。若本期的「深入思考」被写在最后一张卡里面（`.deep-title`），就把它挪出来放到两节之后，别让两节夹在卡片中间。这条与 routine prompt 里的页面结构清单冲突时以这里为准。

1. **越界 · 跨学科的联想**（2026-10-17 起，必写，3–5 条）：写本期某条写作原则和另一个领域的什么东西是同一个结构，一两句说清像在哪、不像在哪。**每条约 60–90 字**，只有展开的那 1 条可到约 120 字。
   - 优先挂读者的深度兴趣：认知科学、信息论、神经科学、语言学、佛学、意识、心理学、东西方哲学、生物进化、复杂性科学、分布式系统；旁支领导力、投资、商业。**别挂回写作自己的地盘**：修辞学、文学理论、出版、编辑、其他写作流派都不算越界。
   - 提到的具体研究、人物、年份必须真实准确，拿不准就换一条。
   - 「名家原话」「关键参考」里名家自己说的东西进正文；**我们联想到的只进越界**，不写进原则卡。和本期「深入思考」已经展开的跨界话题**不重复**。
   - 中文 h2 `越界 · 跨学科的联想`，英文页 h2 `Crossovers`。
2. **十条要点**（2026-10-17 起，必写，**正好 10 条**）：读者直接拿它记笔记。每条一句完整的话，约 20–45 字，**单独抄出去也能看懂**：写出原则名和概念名，不用「它」「这一招」这类要靠上下文的代词。人名不必每条都当主语开头：全组里名家的名字出现两三次就够，其余各条直接写原则、机制或做法（写「人物靠压力下的选择立起来，不靠形容词」，不写「契诃夫认为……」）。覆盖四张原则卡最值得记的原则、机制和常见错误，以及越界里的一两条；顺序跟正文走。**只总结正文已经写过的东西**，不加新信息，不放引语，不放习作题和思考题。中文 h2 `十条要点`，英文页 h2 `Ten takeaways`。

骨架（英文页同结构，只换标题和内容）：

```html
<section class="xbox cx">
<h2>越界 · 跨学科的联想</h2>
<div class="crossx"><ul>
<li><b>认知科学 · 组块</b>：……</li>
</ul></div>
</section>
<section class="xbox tk">
<h2>十条要点</h2>
<ol class="takeaways">
<li>……</li>
</ol>
</section>
```

`.crossx` 里面不要再套 `<div>`（闸门按第一个 `</div>` 截取条目）。

CSS（旧页的 `<style>` 里没有这段，写新页时**追加到 `<style>` 末尾、`@media` 之前**；配色沿用本仓的墨黑 + 暗金）：

```css
.xbox{background:#fff;border-radius:2px;box-shadow:0 1px 6px rgba(0,0,0,0.06);padding:30px 32px;margin-bottom:36px;border-top:3px solid #8a7a4a}
.xbox.tk{border-top-color:#1f1f1f}
.xbox h2{font-size:1.3rem;font-weight:700;margin-bottom:16px;color:#1f1f1f}
.crossx ul{list-style:none;margin:0;padding:0}
.crossx li{padding:12px 0;border-top:1px solid #e0ddd4;font-size:0.96rem;color:#2a2a2a;line-height:1.8}
.crossx li:first-child{border-top:none;padding-top:0}
.crossx b{color:#8a7a4a;font-family:Georgia,serif}
.takeaways{counter-reset:tk;list-style:none;margin:0;padding:0;background:#f8f6f1;border:1px solid #d8d0bc;border-radius:2px}
.takeaways li{counter-increment:tk;position:relative;padding:11px 18px 11px 52px;border-top:1px solid #e8e2d2;font-size:0.96rem;color:#2a2a2a;line-height:1.75}
.takeaways li:first-child{border-top:none}
.takeaways li::before{content:counter(tk,decimal-leading-zero);position:absolute;left:18px;top:12px;font-family:Georgia,serif;font-size:0.8rem;font-weight:700;color:#8a7a4a}
```

`@media(max-width:600px)` 里再加一行 `.xbox{padding:24px 20px}`，和 `.card` 一致。

篇幅：越界约 400 字、十条要点约 350 字，`.maxchars` 已为这两节从 3500 上调到 4250（2026-10-17）；原则卡和深入思考的篇幅不跟着涨。

`publish.sh` 对**从未提交过的新页**（中英两页都查）卡两道闸：十条要点正好 10 个 `<li>`；越界框存在且 3–5 个 `<li>`。旧页不查。
