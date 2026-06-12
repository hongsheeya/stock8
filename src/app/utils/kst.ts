function readPart(parts: Intl.DateTimeFormatPart[], type: string): string {
    return parts.find((item) => item.type === type)?.value || '';
}

function kstParts(date: Date = new Date()) {
    const parts = new Intl.DateTimeFormat('en-CA', {
        timeZone: 'Asia/Seoul',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
    }).formatToParts(date);

    return {
        year: readPart(parts, 'year'),
        month: readPart(parts, 'month'),
        day: readPart(parts, 'day'),
        hour: readPart(parts, 'hour'),
        minute: readPart(parts, 'minute'),
        second: readPart(parts, 'second'),
    };
}

export function kstDateString(date: Date = new Date()): string {
    const parts = kstParts(date);
    return `${parts.year}-${parts.month}-${parts.day}`;
}

export function kstDateTimeString(date: Date = new Date()): string {
    const parts = kstParts(date);
    return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`;
}
