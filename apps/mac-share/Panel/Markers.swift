// Turns Adborth comments into Final Cut markers.
//
// Final Cut gives an extension no call for adding a marker to the open
// timeline. What it does give is the project as FCPXML when the project is
// dragged onto the panel, and it will take FCPXML back. So the comments are
// written into a copy of the project: each becomes a to-do marker on whichever
// clip is under that moment, named with who said it and what they said, with
// the replies in the marker's note. A resolved comment arrives ticked off.
import Foundation

/// A time as Final Cut writes it: a whole number of seconds, or a fraction.
struct Rational: Comparable {
    var num: Int64
    var den: Int64

    init(_ num: Int64, _ den: Int64 = 1) {
        let sign: Int64 = den < 0 ? -1 : 1
        let divisor = Rational.gcd(abs(num), abs(den))
        self.num = sign * num / max(divisor, 1)
        self.den = sign * den / max(divisor, 1)
    }

    /// "3600s", "1001/30000s", "12.5s".
    init?(_ text: String?) {
        guard var text = text?.trimmingCharacters(in: .whitespaces), text.hasSuffix("s") else { return nil }
        text.removeLast()
        let parts = text.split(separator: "/")
        if parts.count == 2, let n = Int64(parts[0]), let d = Int64(parts[1]), d != 0 { self.init(n, d) }
        else if parts.count == 1, let n = Int64(parts[0]) { self.init(n, 1) }
        else if parts.count == 1, let value = Double(parts[0]) { self.init(Int64((value * 60000).rounded()), 60000) }
        else { return nil }
    }

    static let zero = Rational(0)
    var seconds: Double { Double(num) / Double(den) }
    var text: String { den == 1 ? "\(num)s" : "\(num)/\(den)s" }

    private static func gcd(_ a: Int64, _ b: Int64) -> Int64 { b == 0 ? a : gcd(b, a % b) }
    static func + (a: Rational, b: Rational) -> Rational { Rational(a.num * b.den + b.num * a.den, a.den * b.den) }
    static func - (a: Rational, b: Rational) -> Rational { Rational(a.num * b.den - b.num * a.den, a.den * b.den) }
    static func * (a: Rational, k: Int64) -> Rational { Rational(a.num * k, a.den) }
    static func < (a: Rational, b: Rational) -> Bool { a.num * b.den < b.num * a.den }
    static func == (a: Rational, b: Rational) -> Bool { a.num * b.den == b.num * a.den }
}

/// One comment thread, ready to become a marker.
struct MarkerComment {
    var seconds: Double      // from the start of the video
    var title: String        // "Name: what they said"
    var note: String         // the replies, one a line
    var done: Bool           // resolved in Adborth
}

struct MarkerResult {
    var xml: String
    var projectName: String
    var placed: Int
    var alreadyThere: Int
}

enum MarkerError: LocalizedError {
    case notAProject
    var errorDescription: String? {
        "That is not a Final Cut project. Drag a project from the browser, not a clip or an event."
    }
}

enum MarkerBuilder {
    /// Children that must come after a clip's markers; a marker goes before the first of them.
    private static let afterMarkers: Set<String> = [
        "audio-channel-source", "audio-role-source", "sync-source",
        "filter-video", "filter-video-mask", "filter-audio", "metadata", "reserved",
    ]
    private static let clips: Set<String> = [
        "audio", "video", "clip", "title", "mc-clip", "ref-clip", "sync-clip", "asset-clip", "gap", "live-drawing",
    ]

    static func addMarkers(to fcpxml: String, comments: [MarkerComment], nameSuffix: String = " – Adborth comments",
                           clipSuffix: String = " – Adborth markers",
                           library: URL? = nil, event: String? = nil) throws -> MarkerResult {
        let document = try XMLDocument(xmlString: fcpxml, options: [.nodePreserveWhitespace])
        guard let project = try document.nodes(forXPath: "//project").first as? XMLElement,
              let sequence = project.elements(forName: "sequence").first,
              let spine = sequence.elements(forName: "spine").first else { throw MarkerError.notAProject }

        // The project's frame length and where its timecode starts.
        var frame = Rational(1, 25)
        if let formatID = sequence.attribute(forName: "format")?.stringValue,
           let format = try document.nodes(forXPath: "//resources/format[@id='\(formatID)']").first as? XMLElement,
           let length = Rational(format.attribute(forName: "frameDuration")?.stringValue), length > .zero {
            frame = length
        }
        let start = Rational(sequence.attribute(forName: "tcStart")?.stringValue) ?? .zero

        // The main storyline's clips, in order, with the stretch of timeline each covers.
        struct Slot { var element: XMLElement; var from: Rational; var to: Rational? }
        var slots: [Slot] = []
        for child in spine.children ?? [] {
            guard let element = child as? XMLElement, let name = element.name, clips.contains(name) || name == "audition" else { continue }
            let from = Rational(element.attribute(forName: "offset")?.stringValue) ?? start
            // An audition holds its picks inside; the first is the one in use.
            let target = name == "audition" ? (element.children?.compactMap { $0 as? XMLElement }.first ?? element) : element
            let length = Rational(target.attribute(forName: "duration")?.stringValue)
            slots.append(Slot(element: target, from: from, to: length.map { from + $0 }))
        }
        guard !slots.isEmpty else { throw MarkerError.notAProject }

        var placed = 0, alreadyThere = 0
        for comment in comments.sorted(by: { $0.seconds < $1.seconds }) {
            let frames = Int64((max(0, comment.seconds) / frame.seconds + 0.0001).rounded(.down))
            var moment = start + frame * frames
            // The clip under that moment; past the end, the last clip's last frame.
            var slot = slots.last { $0.from <= moment } ?? slots[0]
            if let end = slot.to, moment >= end { moment = max(slot.from, end - frame) }
            if moment < slot.from { slot = slots[0]; moment = slot.from }

            // A marker's time is counted in its clip's own time, not the timeline's.
            let clipStart = Rational(slot.element.attribute(forName: "start")?.stringValue) ?? .zero
            let local = clipStart + (moment - slot.from)

            let existing = slot.element.elements(forName: "marker").contains {
                $0.attribute(forName: "value")?.stringValue == comment.title.split(whereSeparator: \.isNewline).joined(separator: " ")
                    && Rational($0.attribute(forName: "start")?.stringValue) == local
            }
            if existing { alreadyThere += 1; continue }

            let marker = XMLElement(name: "marker")
            marker.addAttribute(XMLNode.attribute(withName: "start", stringValue: local.text) as! XMLNode)
            marker.addAttribute(XMLNode.attribute(withName: "duration", stringValue: frame.text) as! XMLNode)
            let title = comment.title.split(whereSeparator: \.isNewline).joined(separator: " ")
            marker.addAttribute(XMLNode.attribute(withName: "value", stringValue: title) as! XMLNode)
            marker.addAttribute(XMLNode.attribute(withName: "completed", stringValue: comment.done ? "1" : "0") as! XMLNode)
            if !comment.note.isEmpty {
                // One line: a line break inside an XML attribute does not survive.
                let note = comment.note.split(whereSeparator: \.isNewline).joined(separator: "  •  ")
                marker.addAttribute(XMLNode.attribute(withName: "note", stringValue: note) as! XMLNode)
            }
            let children = slot.element.children ?? []
            let index = children.firstIndex { afterMarkers.contains($0.name ?? "") } ?? children.count
            slot.element.insertChild(marker, at: index)
            placed += 1
        }

        let original = project.attribute(forName: "name")?.stringValue ?? "Project"

        // A second way in: a compound clip of running timecode, as long as the
        // project, carrying every comment as a marker. Laid over any cut of the
        // film, its markers line up by time, whatever has changed underneath.
        var markerClip: XMLElement?
        if let resources = try document.nodes(forXPath: "/fcpxml/resources").first as? XMLElement,
           let length = Rational(sequence.attribute(forName: "duration")?.stringValue), length > .zero {
            func attribute(_ name: String, _ value: String) -> XMLNode { XMLNode.attribute(withName: name, stringValue: value) as! XMLNode }
            let taken = Set(((try? document.nodes(forXPath: "//@id")) ?? []).compactMap(\.stringValue))
            var number = 1
            func freshID() -> String {
                while taken.contains("adborth\(number)") { number += 1 }
                defer { number += 1 }
                return "adborth\(number)"
            }
            let effectID = freshID(), mediaID = freshID()
            let clipName = original + clipSuffix

            let effect = XMLElement(name: "effect")
            effect.addAttribute(attribute("id", effectID))
            effect.addAttribute(attribute("name", "Timecode"))
            effect.addAttribute(attribute("uid", ".../Generators.localized/Elements.localized/Timecode.localized/Timecode.motn"))
            resources.addChild(effect)

            let timecode = XMLElement(name: "video")
            timecode.addAttribute(attribute("ref", effectID))
            timecode.addAttribute(attribute("offset", start.text))
            timecode.addAttribute(attribute("name", "Timecode"))
            timecode.addAttribute(attribute("start", start.text))
            timecode.addAttribute(attribute("duration", length.text))
            let inner = XMLElement(name: "spine")
            inner.addChild(timecode)
            let innerSequence = XMLElement(name: "sequence")
            for name in ["format", "duration", "tcStart", "tcFormat", "audioLayout", "audioRate"] {
                if let value = sequence.attribute(forName: name)?.stringValue { innerSequence.addAttribute(attribute(name, value)) }
            }
            innerSequence.addChild(inner)
            let media = XMLElement(name: "media")
            media.addAttribute(attribute("id", mediaID))
            media.addAttribute(attribute("name", clipName))
            media.addChild(innerSequence)
            resources.addChild(media)

            let clip = XMLElement(name: "ref-clip")
            clip.addAttribute(attribute("ref", mediaID))
            clip.addAttribute(attribute("name", clipName))
            clip.addAttribute(attribute("start", start.text))
            clip.addAttribute(attribute("duration", length.text))
            let last = start + length - frame
            for comment in comments.sorted(by: { $0.seconds < $1.seconds }) {
                let frames = Int64((max(0, comment.seconds) / frame.seconds + 0.0001).rounded(.down))
                var moment = start + frame * frames
                if last < moment { moment = last }
                let marker = XMLElement(name: "marker")
                marker.addAttribute(attribute("start", moment.text))
                marker.addAttribute(attribute("duration", frame.text))
                marker.addAttribute(attribute("value", comment.title.split(whereSeparator: \.isNewline).joined(separator: " ")))
                marker.addAttribute(attribute("completed", comment.done ? "1" : "0"))
                if !comment.note.isEmpty {
                    marker.addAttribute(attribute("note", comment.note.split(whereSeparator: \.isNewline).joined(separator: "  •  ")))
                }
                clip.addChild(marker)
            }
            if let parent = project.parent as? XMLElement {
                parent.insertChild(clip, at: project.index + 1)
                markerClip = clip
            }
        }

        // A copy beside the original, never over it.
        let name = original + nameSuffix
        project.removeAttribute(forName: "name")
        project.addAttribute(XMLNode.attribute(withName: "name", stringValue: name) as! XMLNode)
        project.removeAttribute(forName: "uid")
        project.removeAttribute(forName: "id")

        // Named with its library and event, Final Cut puts the copy beside the
        // original without asking which library it belongs in.
        if let library, let parent = project.parent as? XMLElement, parent.name == "fcpxml" {
            let index = project.index
            project.detach()
            let inEvent = XMLElement(name: "event")
            inEvent.addAttribute(XMLNode.attribute(withName: "name", stringValue: event ?? "Adborth") as! XMLNode)
            inEvent.addChild(project)
            if let markerClip { markerClip.detach(); inEvent.addChild(markerClip) }
            let inLibrary = XMLElement(name: "library")
            inLibrary.addAttribute(XMLNode.attribute(withName: "location", stringValue: library.absoluteString) as! XMLNode)
            inLibrary.addChild(inEvent)
            parent.insertChild(inLibrary, at: index)
        }

        document.isStandalone = false
        return MarkerResult(xml: document.xmlString(options: [.nodePrettyPrint]), projectName: name, placed: placed, alreadyThere: alreadyThere)
    }
}
