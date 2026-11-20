// Deployment template: fill in RES and LOCKED_RESIDENTIAL_IP before importing.
function main(config) {
  // Local applications and SSH reverse-forwards use loopback only.
  config["allow-lan"] = false;
  // ============================================================
  // 智能住宅链路版：
  //   1) Claude/Anthropic + Muse/Meta + Gmail/登录资源 + 账号邮箱(mail.com) 接入 claude-residential
  //      → claude-safe
  //      → claude-residential（完整住宅链自动选择）
  //      → 新加坡/台湾/日本/香港 IEPL
  //      → 固定住宅 SOCKS5
  //   2) OpenAI/ChatGPT/Codex + Gemini/YouTube/通用 DNS/未分类海外
  //      → proxy 普通梯子【固定节点，面板手动选一个，绝不自动跳；防账号风控】
  //   3) 监听端口 7899 → 强制住宅
  //   4) 国内/校园/腾讯系/B站 → DIRECT
  //   5) FPGA Cluster / 校园内网 → TUN 也绕过
  //   6) Sniffer override-destination，修复本地 DNS 污染
  //
  //   固定出口只约束网络路径；服务方仍会依据账号、内容和使用行为进行判定。
  //   IEPL 负责连接住宅服务器，实际出口由独立守卫核验。
  //   claude-residential 保留全部手动候选，默认自动主备只切前置、保持固定出口。
  // ============================================================

  // ---------- 组名 ----------
  const RESIDENTIAL = "claude-residential";
  const RESIDENTIAL_AUTO = "claude-residential-auto";
  const FRONT       = "claude-front";    // 旧组名，仅用于清理
  const SAFE        = "claude-safe";
  const PROXY       = "proxy";           // 普通梯子：固定节点（原 ai-sg，已改名+改为 select）
  const PROXY_SG    = "proxy-sg";        // 旧地区组名，仅用于清理上一版残留
  const PROXY_TW    = "proxy-tw";        // 旧地区组名，仅用于清理上一版残留
  const PROXY_JP    = "proxy-jp";        // 旧地区组名，仅用于清理上一版残留

  const CHAIN_PREFIX = "CLAUDE-CHAIN | ";
  const LEGACY_CHAIN_PREFIXES = ["MY-CHAIN | "];
  const isGeneratedChainName = name =>
    [CHAIN_PREFIX, ...LEGACY_CHAIN_PREFIXES].some(prefix =>
      String(name || "").startsWith(prefix));

  // 测速覆盖前置节点、住宅 SOCKS5 和目标网站；远端守卫核验 Anthropic 和固定出口。

  // ---------- 住宅 SOCKS5 ----------
  const RES = {
    server: "203.0.113.10",
    port: 443,
    user: "YOUR_PROXY_USERNAME",
    pass: "YOUR_PROXY_PASSWORD"
  };
  const LOCKED_RESIDENTIAL_IP = "203.0.113.10";

  // 核对固定住宅入口 IP；实际出口仍由远端守卫运行时验证。
  if (RES.server !== LOCKED_RESIDENTIAL_IP) {
    throw new Error(
      `Claude residential 必须锁定出口 ${LOCKED_RESIDENTIAL_IP}`
    );
  }

  // ---------- 节点筛选 ----------
  const IEPL = /IEPL/i;
  const REGION = {
    sg: /新加坡|Singapore|狮城|\bSG(?=\d|\b)/i,
    tw: /台湾|台灣|臺灣|Taiwan|台北|臺北|Taipei|\bTW(?=\d|\b)/i,
    jp: /日本|Japan|东京|東京|Tokyo|大阪|Osaka|\bJP(?=\d|\b)/i,
    hk: /香港|HongKong|Hong\s?Kong|\bHK(?=\d|\b)/i,
    us: /美国|美國|United\s?States|USA/i
  };
  const preferFront = new RegExp(
    [REGION.sg, REGION.tw, REGION.jp, REGION.hk, REGION.us]
      .map(pattern => pattern.source)
      .join("|"),
    "i"
  );

  // ---------- DNS ----------
  const doh         = g => [`https://1.1.1.1/dns-query#${g}`, `https://1.0.0.1/dns-query#${g}`];
  const domesticDns = ["119.29.29.29", "223.5.5.5"];
  const campusDns   = [...domesticDns]; // Set your campus DNS here if needed.
  // 国内加密 DoH（阿里 / 腾讯）：用于解析代理节点域名，GFW 看不到查询内容，避免代理节点解析被污染。
  // 全用 IP 直连，无需二次解析、无引导死循环。
  const bootstrapDoh = ["https://223.5.5.5/dns-query", "https://1.12.12.12/dns-query"];

  // ---------- 校园 / FPGA 内网（TUN 也绕过）----------
  const campusIpCidrs = []; // Fill in your own campus SSH / Jetson exclusions.

  // ---------- 域名表（纯数据，集中维护）----------
  const D = {
    campus: ["hkust-gz.edu.cn", "hkust.edu.hk", "ust.hk"],

    direct: [
      "bilibili.com", "bilivideo.com", "bilivideo.cn", "hdslb.com",
      "biliapi.com", "biliapi.net", "biliimg.com",
      "qq.com", "qq.com.cn", "weixin.qq.com", "wx.qq.com", "wechat.com", "weixinbridge.com",
      "qpic.cn", "qlogo.cn", "gtimg.cn", "gtimg.com", "idqqimg.com", "qqmail.com",
      "tencent.com", "tencent-cloud.cn", "myqcloud.com", "qcloud.com", "dnspod.cn",
      "alipay.com", "alipayobjects.com", "taobao.com", "tmall.com", "alicdn.com",
      "jd.com", "360buyimg.com", "163.com", "126.net", "netease.com", "music.163.com",
      "douyin.com", "douyinpic.com", "douyinvod.com", "bytedance.com",
      "weibo.com", "weibocdn.com", "sinaimg.cn", "zhihu.com", "zhimg.com", "xiaohongshu.com",
      "todesk.com", "todesk.cn", "dbase2.gslib.com.cn", "cnki.net"
    ],

    claudeSuffix: ["anthropic.com", "claude.ai", "claude.com", "claudeusercontent.com"],

    // Muse / Meta 主站、API、登录、社交服务与静态资源；后缀覆盖全部子域名。
    // ai.meta.com/muse 是 URL，域名规则应写 meta.com。
    metaMuseSuffix: [
      "muse.ai", "meta.ai", "meta.com", "atmeta.com", "metaaivm.com", "llama.com",
      "facebook.com", "facebook.net", "facebookmail.com", "fb.com", "fb.me", "fb.gg",
      "fb.watch", "fbwat.ch", "fburl.com", "fbcdn.com", "fbcdn.net",
      "fbsbx.com", "fbsbx.net", "tfbnw.net", "accountkit.com",
      "instagram.com", "cdninstagram.com", "igcdn.com", "ig.me",
      "messenger.com", "fbmessenger.com", "m.me", "threads.com", "threads.net",
      "whatsapp.com", "whatsapp.net", "whatsapp.org", "whatsappbrand.com", "wa.me",
      "oculus.com", "oculuscdn.com", "oculusvr.com", "ocul.us"
    ],
    metaMuseExact: ["fbcdn-a.akamaihd.net"],

    openaiSuffix: ["chatgpt.com", "openai.com", "oaistatic.com", "oaiusercontent.com", "openaiusercontent.com"],
    openaiExact:  ["auth.openai.com", "billing.openai.com", "platform.openai.com", "api.openai.com",
                   "chat.openai.com", "chatgpt.com", "ab.chatgpt.com", "ios.chat.openai.com", "desktop.chatgpt.com"],

    googleSuffix: ["google.com", "googleapis.com", "gstatic.com", "googleusercontent.com"],
    googleExact:  ["gemini.google.com", "bard.google.com", "aistudio.google.com", "ai.google.dev",
                   "generativelanguage.googleapis.com", "accounts.google.com", "oauth2.googleapis.com",
                   "apis.google.com", "ogs.google.com"],

    // Gmail dependencies from Google Workspace's firewall list, plus Gmail API.
    gmailSuffix: ["gmail.com", "googlemail.com", "mail.google.com", "mail-attachment.google.com",
                  "googleusercontent.com", "client-channel.google.com", "clients.google.com", "clients6.google.com"],
    gmailExact: ["accounts.google.com", "apis.google.com", "contacts.google.com", "ogs.google.com",
                 "play.google.com", "ssl.gstatic.com", "www.gstatic.com", "www.google.com",
                 "oauth2.googleapis.com", "gmail.googleapis.com", "www.googleapis.com"],
    gmailClientsPattern: String.raw`^([^.]+\.)*clients[^.]*\.google\.com$`,

    media: ["youtube.com", "youtu.be", "youtube-nocookie.com", "googlevideo.com", "ytimg.com", "ggpht.com"],
    ordinarySuffix: ["openreview.net"],

    residentialSuffix: [
      "mail.com", "mail.net",                    // Claude 注册邮箱，与 Claude 共用固定住宅出口
      "openrouter.ai", "openrouter.com",
      "cursor.com", "cursor.sh", "cursorapi.com", "cursor-cdn.com",
      "auth0.com", "arkoselabs.com", "githubusercontent.com",
      "statsig.com", "statsig.io", "datadoghq.com", "sentry.io", "segment.io", "segment.com", "launchdarkly.com",
      "dnsleaktest.com", "browserleaks.com",
      "ipify.org", "ifconfig.me", "ipinfo.io", "ip-api.com", "ip.sb", "icanhazip.com", "ident.me",
      "net.coffee", "ping0.cc", "ping0.xyz", "whoer.net", "ipleak.net", "anyrouter.top"
    ],
    residentialExact: [
      "api2.cursor.sh", "api3.cursor.sh", "api4.cursor.sh", "api5.cursor.sh", "repo42.cursor.sh",
      "us-asia.gcpp.cursor.sh", "us-eu.gcpp.cursor.sh", "us-only.gcpp.cursor.sh",
      "marketplace.cursorapi.com", "downloads.cursor.com",
      "anysphere-binaries.s3.us-east-1.amazonaws.com",
      "cloudflare-dns.com", "dns.google", "one.one.one.one", "dns.quad9.net", "doh.opendns.com",
      "api.ipify.org", "ifconfig.me", "ipinfo.io", "ip-api.com", "ip.net.coffee", "ip.ping0.cc"
    ]
  };

  // claude 域名 + 其它住宅域名（都走住宅 safe 组）
  const residentialSuffixAll = [...D.claudeSuffix, ...D.residentialSuffix, ...D.gmailSuffix];

  // ---------- 分流路由表（数组顺序 = 匹配优先级）----------
  const ROUTES = [
    { // Muse / Meta 及关联服务 → 固定住宅；DNS 同走住宅出口
      group: RESIDENTIAL, doh: doh(RESIDENTIAL),
      suffix: D.metaMuseSuffix, exact: D.metaMuseExact,
      quicSuffix: D.metaMuseSuffix
    },
    { // OpenReview 主站及 API → 普通 proxy
      group: PROXY, doh: doh(PROXY),
      suffix: D.ordinarySuffix
    },
    { // YouTube / 视频 → proxy
      group: PROXY, doh: doh(PROXY),
      suffix: D.media
    },
    { // OpenAI / ChatGPT / Codex → proxy（固定普通节点）
      group: PROXY, doh: doh(PROXY),
      suffix: D.openaiSuffix, exact: D.openaiExact, keyword: ["openai", "chatgpt"],
      quicSuffix: D.openaiSuffix, quicKeyword: ["openai", "chatgpt"]
    },
    { // Google / Gemini → proxy；Gmail 与共用登录资源由前置住宅规则覆盖
      group: PROXY, doh: doh(PROXY),
      suffix: D.googleSuffix, exact: D.googleExact, keyword: ["google"],
      quicSuffix: D.googleSuffix, quicKeyword: ["google"]
    },
    { // 各网站共用的 Cloudflare 验证组件 → proxy，与普通网站保持同一出口
      group: PROXY, doh: doh(PROXY),
      suffix: ["cloudflare.com", "cloudflareinsights.com"]
    },
    { // Claude + 住宅域名 → 住宅 safe；解析走住宅出口
      group: SAFE, doh: doh(RESIDENTIAL),
      suffix: residentialSuffixAll, exact: [...D.residentialExact, ...D.gmailExact], keyword: ["anthropic", "claude"],
      quicSuffix: D.claudeSuffix, quicKeyword: ["anthropic", "claude"]
    }
  ];

  // ---------- 小工具 ----------
  const dedupe = a => Array.from(new Set(a));

  const domainRules = ({ group, suffix = [], exact = [], keyword = [] }) => [
    ...suffix.map(d  => `DOMAIN-SUFFIX,${d},${group}`),
    ...exact.map(d   => `DOMAIN,${d},${group}`),
    ...keyword.map(k => `DOMAIN-KEYWORD,${k},${group}`)
  ];

  const quicRules = ({ quicSuffix = [], quicKeyword = [] }) => [
    ...quicSuffix.map(d  => `AND,((DOMAIN-SUFFIX,${d}),(NETWORK,udp)),REJECT`),
    ...quicKeyword.map(k => `AND,((DOMAIN-KEYWORD,${k}),(NETWORK,udp)),REJECT`)
  ];

  // ============================================================
  // 初始化
  // ============================================================
  config["ipv6"] = false;
  // 消除不同协议握手方式造成的虚假延迟差异，比较稳定链路 RTT。
  config["unified-delay"] = true;

  config["tun"] = Object.assign({}, config["tun"] || {}, {
    "auto-route": true,
    "auto-detect-interface": true,
    "route-exclude-address": dedupe([
      ...((config["tun"] && config["tun"]["route-exclude-address"]) || []),
      ...campusIpCidrs
    ])
  });

  config["profile"] = config["profile"] || {};
  config["profile"]["store-selected"] = true;   // 关键：记住你在 proxy 组手动选的固定节点

  config["proxies"]      = config["proxies"]      || [];
  config["proxy-groups"] = config["proxy-groups"] || [];
  config["rules"]        = config["rules"]        || [];

  const originalProxies = config["proxies"];
  const proxyByName = new Map(originalProxies.map(p => [p.name, p]));

  // NCloud / iKuu 等机场常把流量、到期时间和官网提示伪装成节点。
  // 这些项目不能进入业务策略组，也不能作为住宅链前置。
  const INFO_NODE = /(?:剩余流量|距离下次重置|套餐到期|到期时间|youtunice\.com|官网|请勿|跳转域名|故障转移|traffic|expire|official|website)/i;
  const isUsableProxy = p => p && p.name &&
    !["REJECT", "DIRECT", "PASS", "COMPATIBLE"].includes(p.name) &&
    p.name !== RESIDENTIAL && !isGeneratedChainName(p.name) &&
    !INFO_NODE.test(p.name);

  // 以实际 proxies 为准，不依赖机场策略组的名称或结构。
  const allUsableNodeNames = originalProxies
    .filter(isUsableProxy)
    .map(p => p.name);

  // ---------- 选 IEPL 节点 ----------
  const candidateGroup = config["proxy-groups"].find(g =>
    /^(?:Alagent|NCloud|iKuu|CLAUDE|自动选择|节点选择)$/i.test(g.name));

  const isFront = name => {
    const p = proxyByName.get(name);
    return p && name !== RESIDENTIAL &&
      !isGeneratedChainName(name) && IEPL.test(name);
  };

  // 候选组可能只列出一部分节点，因此必须与全部原始 IEPL 合并。
  const candidateIeplPool =
    (candidateGroup && Array.isArray(candidateGroup.proxies))
    ? candidateGroup.proxies.filter(isFront)
    : [];

  const allOriginalIepl = originalProxies
    .filter(p => p && p.name && isFront(p.name))
    .map(p => p.name);

  let ieplPool = dedupe([
    ...candidateIeplPool,
    ...allOriginalIepl
  ]);

  // 新机场可能完全没有名为 IEPL 的节点。此时允许所有真实节点作为前置，
  // 否则 claude-residential 会只剩 REJECT。
  if (!ieplPool.length) ieplPool = allUsableNodeNames.slice();

  // 面板保留全部完整链路，所有候选使用同一个固定 SOCKS5 出口。
  const matchedFrontProxies = ieplPool.filter(n => preferFront.test(n));
  let frontProxies = dedupe([
    ...matchedFrontProxies.filter(n => REGION.hk.test(n)),
    ...matchedFrontProxies.filter(n => REGION.sg.test(n)),
    ...matchedFrontProxies.filter(n => REGION.jp.test(n)),
    ...matchedFrontProxies.filter(n => REGION.tw.test(n)),
    ...matchedFrontProxies.filter(n => REGION.us.test(n))
  ]);
  if (!frontProxies.length) frontProxies = ieplPool.slice();

  // ---------- 普通梯子节点池 ----------
  // 普通 proxy 组应收集全部真实节点；IEPL 只是链路类型，不能成为
  // NCloud/iKuu 的兼容门槛。
  const ieplNames = allUsableNodeNames;

  // proxy 组节点顺序：新加坡 → 台湾 → 日本 → 香港 → 美国 → 其它（兜底，避免漏节点）。
  // 全是具体节点，无地区自动档。默认落在第一个新加坡节点；store-selected 记住你手动选的那个，重启不变、不自动跳。
  const sortedNodes = [
    ...ieplNames.filter(n => REGION.sg.test(n)),
    ...ieplNames.filter(n => REGION.tw.test(n)),
    ...ieplNames.filter(n => REGION.jp.test(n)),
    ...ieplNames.filter(n => REGION.hk.test(n)),
    ...ieplNames.filter(n => REGION.us.test(n)),
    ...ieplNames.filter(n =>
      !REGION.sg.test(n) && !REGION.tw.test(n) && !REGION.jp.test(n) &&
      !REGION.hk.test(n) && !REGION.us.test(n))
  ];
  const ordered = dedupe(sortedNodes);   // dedupe 防止某节点同时命中两个地区正则被列两次
  const proxyMembers = ordered.length ? ordered : ["REJECT"];

  // ---------- MATCH 兜底：未匹配前述分流规则的代理流量走 proxy（固定节点）----------
  const generalGroup = PROXY;

  // ---------- 清理旧注入项（含旧名 ai-sg*），避免重复 / 残留孤儿组 ----------
  config["proxies"] = originalProxies.filter(p =>
    p.name !== RESIDENTIAL && !isGeneratedChainName(p.name));
  config["proxy-groups"] = config["proxy-groups"].filter(g =>
    ![FRONT, SAFE, RESIDENTIAL, RESIDENTIAL_AUTO, PROXY, "openai", PROXY_SG, PROXY_TW, PROXY_JP,
      "ai-sg", "ai-sg-sg", "ai-sg-tw", "ai-sg-jp", "gemini-sg"].includes(g.name));

  // ---------- 为每个 IEPL 生成一条完整住宅链 ----------
  // 每个测速成员的实际路径：
  // 本机 → 具体 IEPL → 固定住宅 SOCKS5 → Claude
  const chainProxyNames = frontProxies.map(
    frontName => `${CHAIN_PREFIX}${frontName}`);

  // 2026-10-25 同出口实测：三条均通过 120 秒空闲复用；港 S02 优先。
  // 只检查这三条完整链，避免对全部候选同时发起探测。
  const autoMembers = [/香港S02/, /日本S09/, /新加坡S01/].flatMap(
    pattern => chainProxyNames.filter(name => pattern.test(name)));
  if (!autoMembers.length) throw new Error("Claude 自动主备没有已配置的候选链路");

  const chainProxies = frontProxies.map(frontName => ({
    name: `${CHAIN_PREFIX}${frontName}`,
    type: "socks5",
    server: RES.server,
    port: RES.port,
    username: RES.user,
    password: RES.pass,
    udp: false,
    "dialer-proxy": frontName
  }));

  // AdsPower traffic must pass the fixed-IP gate, including unclassified hosts.
  config["proxies"] = config["proxies"].filter(p => p.name !== "claude-browser-guard");
  config["proxies"].unshift({
    name: "claude-browser-guard", type: "http", server: "127.0.0.1", port: 17899
  }, ...chainProxies);
  if (!chainProxyNames.length) chainProxyNames.push("REJECT");

  // ---------- 策略组 ----------
  // claude-residential 保留全部手动候选，并提供仅切前置的自动主备。
  const sel = (name, proxies, extra = {}) => Object.assign({
    name, type: "select", proxies
  }, extra);

  const myGroups = [
    sel(SAFE, [RESIDENTIAL, "REJECT"], {
      "disable-udp": true
    }),
    sel(RESIDENTIAL, [RESIDENTIAL_AUTO, ...chainProxyNames], {
      "disable-udp": true, "default-selected": RESIDENTIAL_AUTO
    }),
    {
      name: RESIDENTIAL_AUTO, type: "fallback", proxies: autoMembers,
      url: "https://www.gstatic.com/generate_204", "expected-status": "204",
      interval: 60, timeout: 5000, lazy: true,
      "max-failed-times": 2, "disable-udp": true
    },
    sel(PROXY, proxyMembers)                         // 普通梯子：固定节点，手动选，不自动跳
  ];
  config["proxy-groups"] = [...myGroups, ...config["proxy-groups"]];

  // ---------- 强制端口 + 远端反向隧道端口 ----------
  // claude-pipe(7899): 强制住宅，本地 Claude 用
  // agent-pipe(7898): 不强制出口、按规则分流，给 SSH 远端反向隧道用
  //   → 远端 Codex 的 OpenAI 流量走 proxy；Claude Code 的 Anthropic 流量走住宅出口。
  config["listeners"] = (config["listeners"] || []).filter(l =>
    l && l.name !== "claude-pipe" && l.name !== "openai-pipe" && l.name !== "agent-pipe");
  config["listeners"].push({
    name: "claude-pipe", type: "mixed", port: 7899, listen: "127.0.0.1", proxy: SAFE, udp: false
  });
  config["listeners"].push({
    name: "agent-pipe", type: "mixed", port: 7898, listen: "127.0.0.1", udp: false
  });

  // ============================================================
  // 规则（本地 → 进程 → QUIC 拦截 → 分流 → DoH IP → 收尾）
  // ============================================================
  const localRules = [
    "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
    ...campusIpCidrs.map(c => `IP-CIDR,${c},DIRECT,no-resolve`),
    "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
    "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve",
    "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
    "IP-CIDR,169.254.0.0/16,DIRECT,no-resolve",
    "IP-CIDR,224.0.0.0/4,DIRECT,no-resolve",
    ...D.campus.map(d => `DOMAIN-SUFFIX,${d},DIRECT`),
    ...D.direct.map(d => `DOMAIN-SUFFIX,${d},DIRECT`)
  ];

  // Claude CLI → claude-safe → 住宅；Codex/ChatGPT App → proxy
  const todeskProcessRules = [
    "PROCESS-NAME,ToDesk.exe,DIRECT",
    "PROCESS-NAME,ToDesk_Service.exe,DIRECT",
    "PROCESS-NAME,ToDesk_Session.exe,DIRECT",
    "PROCESS-NAME,ToDesk_Lite.exe,DIRECT",
    "PROCESS-NAME,ToDeskUpd.exe,DIRECT",
    "PROCESS-NAME,todesk.exe,DIRECT",
    "PROCESS-NAME,todeskd,DIRECT"
  ];

  const processRules = [
    `PROCESS-NAME,claude,${SAFE}`,
    `PROCESS-NAME,claude.exe,${SAFE}`,
    `PROCESS-NAME,codex,${PROXY}`,
    `PROCESS-NAME,codex.exe,${PROXY}`,
    `PROCESS-NAME,Codex.exe,${PROXY}`,
    `PROCESS-NAME,ChatGPT.exe,${PROXY}`,
    `PROCESS-NAME,chatgpt.exe,${PROXY}`
  ];

  // ---------- QUIC / HTTP3 处理 ----------
  // 密不透风：境外流量一律禁 QUIC（UDP/443）→ 强制回落 TCP 走隧道（中转链路对 UDP 不友好，
  // 且裸 UDP 包易被指纹探测）。放在 localRules 之后：国内直连域名已在 localRules 命中 DIRECT，
  // 其 QUIC 得以保留；其余所有 UDP/443（含 Claude/Google/未分类）在此 REJECT，应用自动转 TCP。
  // 想恢复境外 QUIC（如嫌 YouTube 慢），把下面这行改成 false 即可，会退回逐域名拦截。
  const BLOCK_FOREIGN_QUIC = true;
  const quicRejectRules = BLOCK_FOREIGN_QUIC
    ? ["AND,((NETWORK,udp),(DST-PORT,443)),REJECT"]
    : ROUTES.flatMap(quicRules);
  // Claude 域名优先于直连 IP 和其它进程规则；住宅链不支持 UDP 时明确拒绝，
  // 避免 Mihomo 继续向下匹配到普通 proxy 或 DIRECT。
  const claudeDomainRules = domainRules({
    group: SAFE, suffix: D.claudeSuffix, keyword: ["anthropic", "claude"]
  });
  const claudeUdpRejectRules = [
    ...D.claudeSuffix.map(d => `AND,((DOMAIN-SUFFIX,${d}),(NETWORK,udp)),REJECT`),
    ...["anthropic", "claude"].map(k => `AND,((DOMAIN-KEYWORD,${k}),(NETWORK,udp)),REJECT`),
    "AND,((PROCESS-NAME,claude),(NETWORK,udp)),REJECT",
    "AND,((PROCESS-NAME,claude.exe),(NETWORK,udp)),REJECT"
  ];
  // Muse / Meta 优先于直连 IP 和进程规则；住宅 SOCKS5 不支持 UDP。
  const metaMuseUdpRejectRules = [
    ...D.metaMuseSuffix.map(d => `AND,((DOMAIN-SUFFIX,${d}),(NETWORK,udp)),REJECT`),
    ...D.metaMuseExact.map(d => `AND,((DOMAIN,${d}),(NETWORK,udp)),REJECT`)
  ];
  const metaMuseDomainRules = domainRules(ROUTES[0]);
  const gmailDomainRules = [
    ...domainRules({ group: SAFE, suffix: D.gmailSuffix, exact: D.gmailExact }),
    `DOMAIN-REGEX,${D.gmailClientsPattern},${SAFE}`
  ];
  const gmailUdpRejectRules = [
    ...quicRules({ quicSuffix: [...D.gmailSuffix, ...D.gmailExact] }),
    `AND,((DOMAIN-REGEX,${D.gmailClientsPattern}),(NETWORK,udp)),REJECT`
  ];
  const routingRules = ROUTES.slice(1).flatMap(domainRules);

  // DoH 服务器 IP 兜底：Cloudflare(1.1.1.1) 仍归住宅；其它公共 DNS 归 proxy
  const dnsIpRules = [
    `IP-CIDR,1.1.1.1/32,${SAFE},no-resolve`,
    `IP-CIDR,1.0.0.1/32,${SAFE},no-resolve`,
    `IP-CIDR,8.8.8.8/32,${PROXY},no-resolve`,
    `IP-CIDR,8.8.4.4/32,${PROXY},no-resolve`,
    `IP-CIDR,9.9.9.9/32,${PROXY},no-resolve`,
    `IP-CIDR,149.112.112.112/32,${PROXY},no-resolve`
  ];

  const tailRules = ["GEOIP,CN,DIRECT", `MATCH,${generalGroup}`];

  config["rules"] = [
    "AND,((PROCESS-NAME,SunBrowser.exe),(NETWORK,udp)),REJECT",
    "PROCESS-NAME,SunBrowser.exe,claude-browser-guard",
    ...gmailUdpRejectRules,
    ...gmailDomainRules,
    ...metaMuseUdpRejectRules,
    ...metaMuseDomainRules,
    ...claudeUdpRejectRules,
    ...claudeDomainRules,
    ...localRules,
    ...todeskProcessRules,
    ...quicRejectRules,    // 紧跟 localRules：国内直连保 QUIC，其余 UDP/443 一律 TCP
    ...processRules,
    ...routingRules,
    ...dnsIpRules,
    ...tailRules
  ];

  // ============================================================
  // DNS
  // ============================================================
  const oldDns = config["dns"] || {};
  const dnsPolicy = Object.assign({}, oldDns["nameserver-policy"] || {});

  ROUTES.forEach(({ doh: exit, suffix = [], exact = [] }) => {
    suffix.forEach(d => { dnsPolicy[`+.${d}`] = exit; });
    exact.forEach(d  => { dnsPolicy[d]       = exit; });
  });
  D.campus.forEach(d => { dnsPolicy[`+.${d}`] = campusDns; });
  D.direct.forEach(d => { dnsPolicy[`+.${d}`] = domesticDns; });

  config["dns"] = Object.assign({}, oldDns, {
    enable: true,
    ipv6: false,
    listen: "0.0.0.0:53",
    "enhanced-mode": "fake-ip",
    "fake-ip-range": "198.18.0.1/16",
    "use-hosts": true,
    "use-system-hosts": true,
    "respect-rules": true,

    "fake-ip-filter": dedupe([
      ...(oldDns["fake-ip-filter"] || []),
      "+.lan", "+.local", "+.localdomain", "localhost",
      "*.in-addr.arpa", "*.ip6.arpa",
      // NTP 时间同步 + 系统在线检测：需要真实 IP，否则可能时间漂移 / 误报无网络
      "+.ntp.org", "+.pool.ntp.org", "time.windows.com", "+.time.apple.com",
      "+.msftconnecttest.com", "+.msftncsi.com", "captive.apple.com",
      ...D.campus.map(d => `+.${d}`),
      ...D.direct.map(d => `+.${d}`)
    ]),

    "proxy-server-nameserver": bootstrapDoh,   // 加密解析节点域名，不再明文暴露给 GFW
    "default-nameserver": domesticDns,         // 仅用于引导 DoH 主机名（本配置 DoH 均为 IP，几乎用不到），保留明文 IP
    nameserver: doh(PROXY),     // 通用解析走 proxy（固定节点）
    fallback: doh(PROXY),
    "nameserver-policy": dnsPolicy
  });

  // ============================================================
  // Sniffer
  // ============================================================
  config["sniffer"] = Object.assign({}, config["sniffer"] || {}, {
    enable: true,
    "force-dns-mapping": true,
    "parse-pure-ip": true,
    "override-destination": true,
    sniff: {
      TLS:  { ports: [443] },
      HTTP: { ports: [80, "8080-8880"] }
    },
    "skip-domain": dedupe([
      ...((config["sniffer"] && config["sniffer"]["skip-domain"]) || []),
      "+.push.apple.com", "+.apple.com", "+.icloud.com"
    ])
  });

  return config;
}
