export function createSessionTransport(getAccessToken: () => Promise<string>) {
  const controller = new AbortController()
  return {
    signal: controller.signal,
    async auth() {
      if (controller.signal.aborted) throw new Error("Session changed")
      const token = await getAccessToken()
      if (controller.signal.aborted) throw new Error("Session changed")
      return token
    },
    dispose() {
      controller.abort()
    },
  }
}
