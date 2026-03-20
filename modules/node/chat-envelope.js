const ENVELOPE_PREFIX = /^\[([^\]]+)\]\s*/;
const ENVELOPE_CHANNELS = [
  'WebChat',
  'WhatsApp',
  'Telegram',
  'Signal',
  'Slack',
  'Discord',
  'Google Chat',
  'iMessage',
  'Teams',
  'Matrix',
  'Zalo',
  'Zalo Personal',
  'BlueBubbles',
];

const MESSAGE_ID_LINE = /^\s*\[message_id:\s*[^\]]+\]\s*$/i;

function looksLikeEnvelopeHeader(header) {
  if (/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z\b/.test(header)) {
    return true;
  }
  if (/\d{4}-\d{2}-\d{2} \d{2}:\d{2}\b/.test(header)) {
    return true;
  }
  // 检查 header 是否以已知频道名称开头（可能后跟空格或其他内容）
  return ENVELOPE_CHANNELS.some((label) => {
    const headerLower = header.toLowerCase();
    const labelLower = label.toLowerCase();
    // 匹配标签名称后面可选的空格或其他内容
    return headerLower === labelLower || headerLower.startsWith(`${labelLower} `) || headerLower.startsWith(`${labelLower} -`);
  });
}

function stripEnvelope(text) {
  const match = text.match(ENVELOPE_PREFIX);
  if (!match) {
    return text;
  }
  const header = match[1] ?? '';
  if (!looksLikeEnvelopeHeader(header)) {
    return text;
  }
  return text.slice(match[0].length);
}

function stripMessageIdHints(text) {
  if (!text.includes('[message_id:')) {
    return text;
  }
  const lines = text.split(/\r?\n/);
  const filtered = lines.filter((line) => !MESSAGE_ID_LINE.test(line));
  return filtered.length === lines.length ? text : filtered.join('\n');
}

module.exports = {
  stripEnvelope,
  stripMessageIdHints,
};