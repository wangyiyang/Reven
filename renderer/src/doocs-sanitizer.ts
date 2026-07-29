import sanitizeHtml from "sanitize-html";

const purifier = {
  sanitize(html: string): string {
    return sanitizeHtml(html, {
      allowedTags: sanitizeHtml.defaults.allowedTags.concat(["img", "figure", "figcaption"]),
      allowedAttributes: {
        "*": ["class", "style", "data-*"],
        a: ["href", "title"],
        img: ["src", "alt", "title"],
      },
      allowedSchemes: ["http", "https", "mailto", "tel"],
    });
  },
};

export default purifier;
