// Canonicalize formatting only. Preserve every statement, name and expression
// so the existing VM fixtures can extract complete top-level functions.
const fs = require('node:fs');
const acorn = require('acorn');
const { minify_sync } = require('terser');
let cached;
function html() {
  if (cached) return cached;
  const source = fs.readFileSync('frontend/index.html', 'utf8');
  cached = source.replace(/<script>([\s\S]*?)<\/script>/, (_tag, script) => {
    const code = minify_sync(script, {
      compress: false, mangle: false, ecma: 2022,
      format: { quote_style: 1, comments: false, semicolons: true },
    }).code;
    const program = acorn.parse(code, { ecmaVersion: 'latest' });
    return '<script>\n' + program.body.map(node => code.slice(node.start, node.end)).join('\n') + '\n</script>';
  });
  return cached;
}
module.exports = { html };
if (require.main === module) process.stdout.write(html());
