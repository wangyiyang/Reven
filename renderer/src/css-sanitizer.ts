import * as cssTree from "css-tree";

const forbiddenProperties = new Set(["behavior", "-moz-binding"]);

function isSafeDeclaration(node: cssTree.CssNode): boolean {
  if (node.type !== "Declaration") {
    return false;
  }
  const property = node.property.toLowerCase();
  if (property.includes("\\") || forbiddenProperties.has(property)) {
    return false;
  }
  let safe = true;
  cssTree.walk(node.value, (valueNode) => {
    if (valueNode.type === "Raw" || valueNode.type === "Url") {
      safe = false;
    }
    if (valueNode.type === "Function") {
      const name = valueNode.name.toLowerCase();
      if (name === "expression" || name.includes("\\")) {
        safe = false;
      }
    }
  });
  return safe;
}

export function sanitizeInlineStyle(style: string): string | undefined {
  try {
    const ast = cssTree.parse(style, { context: "declarationList" });
    if (ast.type !== "DeclarationList") {
      return undefined;
    }
    const safeDeclarations: string[] = [];
    ast.children.forEach((node) => {
      if (isSafeDeclaration(node)) {
        safeDeclarations.push(cssTree.generate(node));
      }
    });
    return safeDeclarations.join(";") || undefined;
  } catch {
    return undefined;
  }
}
