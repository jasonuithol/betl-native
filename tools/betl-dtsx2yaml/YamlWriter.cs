/* Minimal indent-aware YAML emitter. betl YAML is simple enough that
 * we don't need a real serializer — string templates with carefully
 * controlled indentation cover everything. */

using System.Text;

namespace Betl.Dtsx2Yaml;

public sealed class YamlWriter
{
    readonly StringBuilder _sb = new();
    int _indent;

    public void Line(string text = "")
    {
        if (text.Length == 0) { _sb.Append('\n'); return; }
        for (int i = 0; i < _indent; ++i) _sb.Append(' ');
        _sb.Append(text);
        _sb.Append('\n');
    }

    public void Comment(string text)
    {
        Line("# " + text);
    }

    public void Indent(int n)      { _indent += n; }

    /* Emit `<key>: |2` followed by `body` as a YAML literal block scalar.
     *
     * SSIS pastes SQL and script bodies verbatim, so the source mixes
     * indentation: some lines flush to column 0, others indented two
     * or four spaces. Without an explicit indent indicator YAML uses
     * the FIRST non-empty content line to determine the block's
     * required indent — any later line with fewer leading spaces
     * terminates the literal early and the document fails to parse.
     *
     * The `|2` indicator pins the required indent at exactly two
     * columns past the parent (= the writer's _indent when the
     * content lines are emitted). Every Line() call prepends _indent
     * spaces, so no content line can dip below the block's indent
     * regardless of the original SQL's mixed leading whitespace.
     *
     * Tabs are expanded to four spaces because YAML rejects tab
     * characters in indentation. We also dedent the global minimum
     * leading-space count before emit — purely a readability win,
     * since the `|2` indicator already keeps parsing unambiguous. */
    public void BlockScalar(string key, string body)
    {
        Line(key + ": |2");
        Indent(2);

        var rawLines = (body ?? string.Empty).Replace("\r\n", "\n").Split('\n');
        for (int i = 0; i < rawLines.Length; ++i)
            rawLines[i] = rawLines[i].Replace("\t", "    ");

        int minLead = int.MaxValue;
        foreach (var line in rawLines)
        {
            if (line.Length == 0) continue;
            int lead = 0;
            while (lead < line.Length && line[lead] == ' ') lead++;
            if (lead == line.Length) continue;  // all-whitespace line
            if (lead < minLead) minLead = lead;
        }
        if (minLead == int.MaxValue) minLead = 0;

        foreach (var line in rawLines)
        {
            if (line.Length == 0) { Line(); continue; }
            int actualLead = 0;
            while (actualLead < line.Length && line[actualLead] == ' ') actualLead++;
            int strip = System.Math.Min(minLead, actualLead);
            Line(line.Substring(strip));
        }

        Indent(-2);
    }

    /* Quote a string for use as a YAML scalar where ambiguity is
     * possible (paths, SQL containing colons, etc.). Single-quoted
     * style with internal '' for embedded quotes — simplest YAML
     * scalar that avoids escape rules. */
    public static string Quote(string s)
    {
        var sb = new StringBuilder(s.Length + 2);
        sb.Append('\'');
        foreach (var c in s) { if (c == '\'') sb.Append("''"); else sb.Append(c); }
        sb.Append('\'');
        return sb.ToString();
    }

    /* Convert an SSIS identifier (containing spaces / special chars
     * etc.) to a betl-friendly step/connection id: lower-snake-case,
     * non-alphanum → _. */
    public static string Id(string raw)
    {
        var sb = new StringBuilder(raw.Length);
        bool wasUnderscore = false;
        foreach (var c in raw)
        {
            if (char.IsLetterOrDigit(c))
            {
                sb.Append(char.ToLowerInvariant(c));
                wasUnderscore = false;
            }
            else
            {
                if (!wasUnderscore) sb.Append('_');
                wasUnderscore = true;
            }
        }
        var s = sb.ToString().Trim('_');
        return s.Length == 0 ? "step" : s;
    }

    public override string ToString() => _sb.ToString();
}
