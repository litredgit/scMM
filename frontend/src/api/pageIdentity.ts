// Document identity also works on internal HTTP origins, where randomUUID is unavailable.
function freshIdentity() {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) =>
    byte.toString(16).padStart(2, '0'),
  ).join('')
}
export let pageId = freshIdentity()
export function renewPageIdentity() {
  pageId = freshIdentity()
}
