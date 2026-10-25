import enTranslations from "./en.json";

export type TranslationDict = typeof enTranslations;

// Recursive path type for dot-notation keys
type NestedKeyOf<ObjectType extends object> = {
  [Key in keyof ObjectType & (string | number)]: ObjectType[Key] extends object
    ? `${Key}` | `${Key}.${NestedKeyOf<ObjectType[Key]>}`
    : `${Key}`;
}[keyof ObjectType & (string | number)];

export type TranslationKey = NestedKeyOf<TranslationDict>;

/**
 * Retrieve translation string for given dot-notation key, substituting {{param}} values.
 */
export function t(key: TranslationKey | string, params?: Record<string, string | number>): string {
  const segments = key.split(".");
  let current: unknown = enTranslations;

  for (const segment of segments) {
    if (current && typeof current === "object" && segment in current) {
      current = (current as Record<string, unknown>)[segment];
    } else {
      current = undefined;
      break;
    }
  }

  if (typeof current !== "string") {
    return key;
  }

  let result = current;
  if (params) {
    for (const [paramKey, paramValue] of Object.entries(params)) {
      result = result.replace(new RegExp(`{{\\s*${paramKey}\\s*}}`, "g"), String(paramValue));
    }
  }

  return result;
}
