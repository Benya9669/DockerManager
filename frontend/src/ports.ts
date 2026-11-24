export type Port = { public: number | null; private: number; type: string };
type Mapping = Port & { public: number };
export type PortGroup = { first: Mapping; last: Mapping };

export function groupPorts(ports: Port[]): PortGroup[] {
  // Equal offsets mean the host and container ports advance together.
  const sorted = ports.filter((p): p is Mapping => !!p.public).sort((a, b) =>
    a.type.localeCompare(b.type) || (a.public - a.private) - (b.public - b.private) || a.public - b.public
  );
  const groups: PortGroup[] = [];
  for (const port of sorted) {
    const group = groups[groups.length - 1];
    if (group && group.last.type === port.type) {
      const last = group.last;
      if (port.public === last.public && port.private === last.private) continue;
      if (port.public === last.public + 1 && port.private === last.private + 1) {
        group.last = port;
        continue;
      }
    }
    groups.push({ first: port, last: port });
  }
  return groups.sort((a, b) =>
    Number(a.first !== a.last) - Number(b.first !== b.last) || a.first.public - b.first.public ||
    a.first.private - b.first.private || a.first.type.localeCompare(b.first.type)
  );
}

export function portLabel({ first, last }: PortGroup) {
  const range = (start: number, end: number) => start === end ? String(start) : `${start}–${end}`;
  const host = range(first.public, last.public);
  const container = range(first.private, last.private);
  return `${host === container ? host : `${host} → ${container}`}/${first.type}`;
}
