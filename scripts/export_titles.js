const fs = require('fs');
const content = fs.readFileSync('index.html', 'utf8');
const m = content.match(/const EMBEDDED_VERSES = (\[[\s\S]*?\]);/);
if (m) {
  const verses = JSON.parse(m[1]);
  const lines = ['verse_number,tantra,section,english_title'];
  verses.forEach(function(v) {
    const title = (v.english_title || '').replace(/"/g, '""');
    const section = (v.section || '').replace(/"/g, '""');
    const tantra = (v.tantra || '').replace(/"/g, '""');
    lines.push('"' + v.verse_number + '","' + tantra + '","' + section + '","' + title + '"');
  });
  fs.writeFileSync('verse_titles.csv', lines.join('\n'), 'utf8');
  console.log('Done. Rows: ' + (lines.length - 1));
}
