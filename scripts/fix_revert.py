f = r"D:\code\inspectagent-cloud\app\agent\state_machine.py"
with open(f, "r", encoding="utf-8") as fp:
    c = fp.read()

# 还原：yield _y({  → yield {
old_count = c.count("yield _y({")
c = c.replace("yield _y({", "yield {")
print(f"还原了 {old_count} 处 yield _y( → yield")

# 也把 yield 行里多出来的右括号清掉（yield _y({...}) 变成 yield {...}) 了）
# 检查一下 yield 结尾的模式
import re
# 把 "yield {...})" 变成 "yield {...}"
c = re.sub(r'(yield \{[^}]*\})\)', r'\1', c)

with open(f, "w", encoding="utf-8") as fp:
    fp.write(c)

print(f"✅ 还原完成")
print(f"    yield 总数: {c.count('yield {')}")
print(f"    yield _y 残留: {c.count('yield _y(')}")
print(f"    _y function 定义残留: {'def _y(' in c}")
