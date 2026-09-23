export function localized(record, language) {
  return record?.[language] ?? record?.en ?? ''
}
