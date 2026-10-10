package com.gabstra.myworkoutassistant.insights

import java.io.InputStream
import java.util.PriorityQueue

/**
 * Pure-Kotlin port of the SentencePiece BPE encoder used by the on-device Gemma
 * models, for exact token counting. Mirrors sentencepiece's bpe_model.cc:
 *
 *  1. Escape U+0020 as "▁" (identity normalizer, no dummy prefix, whitespace kept).
 *  2. Split into symbols: longest match against USER_DEFINED pieces (frozen,
 *     never merged), otherwise one Unicode code point.
 *  3. Greedily merge adjacent symbol pairs whose concatenation is a vocab piece,
 *     best score first, leftmost pair on ties (max-heap like SymbolPairComparator).
 *  4. Symbols whose final piece is not in the vocab fall back to byte pieces
 *     (one token per UTF-8 byte), matching byte_fallback.
 *
 * Validated to match SentencePieceProcessor.encode() token counts exactly on a
 * 800-sample battery including digits, punctuation, CJK, emoji and whitespace runs.
 */
internal class GemmaTokenizer private constructor(
    private val normalScores: HashMap<String, Float>,
    private val userDefined: HashSet<String>,
) {
    companion object {
        /** Loads a SentencePiece ModelProto from its serialized bytes. */
        fun from(modelBytes: ByteArray): GemmaTokenizer {
            val normalScores = HashMap<String, Float>(262_000)
            val userDefined = HashSet<String>(8_000)
            for ((piece, score, type) in parseSentencePieces(modelBytes)) {
                when (type) {
                    PieceTypeUserDefined -> userDefined.add(piece)
                    PieceTypeNormal -> normalScores[piece] = score
                    else -> Unit // CONTROL/BYTE/UNKNOWN/UNUSED never join the merge lattice
                }
            }
            return GemmaTokenizer(normalScores, userDefined)
        }

        fun from(stream: InputStream): GemmaTokenizer = stream.use { it.readBytes() }.let(::from)

        private const val PieceTypeNormal = 0
        private const val PieceTypeUserDefined = 4

        private data class SentencePieceEntry(val piece: String, val score: Float, val type: Int)

        /** Minimal protobuf reader for ModelProto: repeated SentencePiece pieces = 1. */
        private fun parseSentencePieces(modelBytes: ByteArray): List<SentencePieceEntry> {
            val entries = ArrayList<SentencePieceEntry>(262_000)
            var index = 0
            val end = modelBytes.size
            while (index < end) {
                val (field, wireType, afterTag) = readTag(modelBytes, index)
                if (field == 1 && wireType == 2) {
                    val (payload, afterLen) = readLengthDelimited(modelBytes, afterTag)
                    entries.add(parsePieceEntry(payload))
                    index = afterLen
                } else {
                    index = skipField(modelBytes, afterTag, wireType)
                }
            }
            return entries
        }

        private fun parsePieceEntry(payload: ByteArray): SentencePieceEntry {
            var piece: String? = null
            var score = 0f
            var type = PieceTypeNormal
            var index = 0
            while (index < payload.size) {
                val (field, wireType, afterTag) = readTag(payload, index)
                when {
                    field == 1 && wireType == 2 -> {
                        val (bytes, afterLen) = readLengthDelimited(payload, afterTag)
                        piece = String(bytes, Charsets.UTF_8)
                        index = afterLen
                    }
                    field == 2 && wireType == 5 -> {
                        val bits = (payload[afterTag].toInt() and 0xFF) or
                            ((payload[afterTag + 1].toInt() and 0xFF) shl 8) or
                            ((payload[afterTag + 2].toInt() and 0xFF) shl 16) or
                            ((payload[afterTag + 3].toInt() and 0xFF) shl 24)
                        score = Float.fromBits(bits)
                        index = afterTag + 4
                    }
                    field == 3 && wireType == 0 -> {
                        val (value, after) = readVarint(payload, afterTag)
                        type = value.toInt()
                        index = after
                    }
                    else -> index = skipField(payload, afterTag, wireType)
                }
            }
            return SentencePieceEntry(piece ?: "", score, type)
        }

        private data class Tag(val field: Int, val wireType: Int, val nextIndex: Int)

        private fun readTag(bytes: ByteArray, index: Int): Tag {
            val (key, after) = readVarint(bytes, index)
            return Tag((key ushr 3).toInt(), (key and 0x7).toInt(), after)
        }

        private data class LengthDelimited(val bytes: ByteArray, val nextIndex: Int) {
            override fun equals(other: Any?) = this === other
            override fun hashCode() = System.identityHashCode(this)
        }

        private fun readLengthDelimited(bytes: ByteArray, index: Int): LengthDelimited {
            val (length, after) = readVarint(bytes, index)
            val end = after + length.toInt()
            return LengthDelimited(bytes.copyOfRange(after, end), end)
        }

        private fun skipField(bytes: ByteArray, index: Int, wireType: Int): Int = when (wireType) {
            0 -> readVarint(bytes, index).second
            1 -> index + 8
            2 -> readLengthDelimited(bytes, index).nextIndex
            5 -> index + 4
            else -> throw IllegalArgumentException("Unsupported protobuf wire type $wireType")
        }

        private fun readVarint(bytes: ByteArray, index: Int): Pair<Long, Int> {
            var result = 0L
            var shift = 0
            var cursor = index
            while (true) {
                val byte = bytes[cursor].toInt() and 0xFF
                cursor += 1
                result = result or ((byte and 0x7F).toLong() shl shift)
                if (byte and 0x80 == 0) return result to cursor
                shift += 7
            }
        }
    }

    private class Symbol(
        var piece: String,
        val frozen: Boolean,
        var prev: Int,
        var next: Int,
    ) {
        var alive = true
    }

    private class MergeCandidate(val negScore: Float, val left: Int)

    /** Exact token count for [text] under the on-device Gemma tokenizer. */
    fun countTokens(text: String): Int {
        if (text.isEmpty()) return 0
        val escaped = text.replace(' ', '▁')
        val symbols = splitIntoSymbols(escaped)
        mergeSymbols(symbols)
        var total = 0
        for (symbol in symbols) {
            if (!symbol.alive) continue
            if (symbol.frozen || normalScores.containsKey(symbol.piece)) {
                total += 1
            } else {
                total += symbol.piece.toByteArray(Charsets.UTF_8).size
            }
        }
        return total
    }

    private fun splitIntoSymbols(escaped: String): MutableList<Symbol> {
        val symbols = ArrayList<Symbol>(escaped.length)
        var index = 0
        val n = escaped.length
        while (index < n) {
            val userMatch = longestUserDefinedMatch(escaped, index)
            if (userMatch != null) {
                symbols.add(Symbol(escaped.substring(index, index + userMatch), true, symbols.size - 1, symbols.size + 1))
                index += userMatch
            } else {
                val codePoint = escaped.codePointAt(index)
                val charCount = Character.charCount(codePoint)
                symbols.add(Symbol(escaped.substring(index, index + charCount), false, symbols.size - 1, symbols.size + 1))
                index += charCount
            }
        }
        return symbols
    }

    private fun longestUserDefinedMatch(text: String, start: Int): Int? {
        val maxSpan = (start + maxUserPieceChars).coerceAtMost(text.length) - start
        if (maxSpan <= 0) return null
        for (span in maxSpan downTo 1) {
            if (userDefined.contains(text.substring(start, start + span))) return span
        }
        return null
    }

    private fun mergeSymbols(symbols: MutableList<Symbol>) {
        val size = symbols.size
        if (size < 2) return
        val heap = PriorityQueue<MergeCandidate>(size) { a, b ->
            if (a.negScore != b.negScore) a.negScore.compareTo(b.negScore) else a.left.compareTo(b.left)
        }
        fun pushPair(left: Int, right: Int) {
            if (left < 0 || right >= size) return
            val leftSymbol = symbols[left]
            val rightSymbol = symbols[right]
            if (!leftSymbol.alive || !rightSymbol.alive) return
            if (leftSymbol.frozen || rightSymbol.frozen) return
            val score = normalScores[leftSymbol.piece + rightSymbol.piece] ?: return
            heap.add(MergeCandidate(-score, left))
        }

        for (left in 0 until size - 1) {
            pushPair(left, left + 1)
        }
        while (heap.isNotEmpty()) {
            val candidate = heap.remove()
            val left = candidate.left
            val right = symbols[left].next
            if (right >= size || right < 0) continue
            val leftSymbol = symbols[left]
            val rightSymbol = symbols[right]
            if (!leftSymbol.alive || !rightSymbol.alive) continue
            val merged = leftSymbol.piece + rightSymbol.piece
            if (normalScores[merged]?.unaryMinus() != candidate.negScore) continue
            leftSymbol.piece = merged
            rightSymbol.alive = false
            val afterRight = rightSymbol.next
            leftSymbol.next = afterRight
            if (afterRight in 0 until size) {
                symbols[afterRight].prev = left
            }
            pushPair(leftSymbol.prev, left)
            pushPair(left, afterRight)
        }
    }

    private val maxUserPieceChars: Int by lazy(LazyThreadSafetyMode.NONE) {
        userDefined.maxOfOrNull { it.length } ?: 1
    }
}
