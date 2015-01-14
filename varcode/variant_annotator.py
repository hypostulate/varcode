from common import reverse_complement
from variant import Variant
from annot import Annot

import pyensembl
from pyensembl.biotypes import is_coding_biotype


class VariantAnnotator(object):
    def __init__(self, ensembl_release):
        self.ensembl = pyensembl.EnsemblRelease(ensembl_release)


    def variant_gene_ids(self, contig, pos, number_modified_bases=1):
        """
        Parameters
        ----------

        contig : str
            Chromosome or contig name

        pos : int
            Position in the chromosome

        number_modified_bases : int
            How many reference bases were changed or deleted?
        """
        return self.ensembl.gene_ids_at_locus(
            contig, pos, pos + number_modified_bases)


    def variant_transcript_ids(self, contig, pos, number_modified_bases=1):
        """
        Parameters
        ----------

        contig : str
            Chromosome or contig name

        pos : int
            Position in the chromosome

        number_modified_bases : int
            How many reference bases were changed or deleted?
        """
        return self.ensembl.transcript_ids_at_locus(
            contig, pos, pos + number_modified_bases)

    def make_intergenic(self, variant):
        return Annot(
            variant=variant,
            variant_type='intergenic',
            genes=[],
            transcripts={},
            coding_effects={})


    def make_intronic(self, variant, genes, transcripts):
        return Annot(
            variant=variant,
            variant_type='intronic',
            genes=genes,
            transcripts=transcripts,
            coding_effects={})

    def overlaps_any_exon(self, transcript, contig, start, end):
        return any(
            exon.overlaps(contig=contig, start=start, end=end)
            for exon in transcript.exons)

    def group_by(self, records, field_name):
        groups = {}
        for record in records:
            value = getattr(record, field_name)
            if value in groups:
                groups[value].append(record)
            else:
                groups[value] = [record]
        return groups

    def describe_variant(self, contig, pos, ref, alt):
        variant = Variant(contig=contig, pos=pos, ref=ref, alt=alt)
        end_pos = variant.end_pos

        overlapping_genes = self.ensembl.genes_at_locus(
            contig, pos, variant.end_pos)

        if len(overlapping_genes) == 0:
            return self.make_intergenic(variant)

        overlapping_transcripts = self.ensembl.transcripts_at_locus(
                contig, pos, end_pos)

        assert len(overlapping_transcripts) > 0, \
            "No transcripts found for mutation %s:%d %s>%s" % (
                contig, pos, ref, alt)

        # group transcripts by their gene ID
        overlapping_transcript_groups = self.group_by(
            overlapping_transcripts, field_name='gene_id')

        protein_variants = {}
        for transcript in overlapping_transcripts:
            if not is_coding_biotype(transcript.biotype):
                protein_variants[transcript.id] = "non-coding"
                continue

            if not transcript.complete:
                protein_variants[transcript.id] = "incomplete"
                continue

            exonic = self.overlaps_any_exon(
                transcript, contig, start=pos, end=end_pos)

            if not exonic:
                protein_variants[transcript.id] = "intronic"
                continue

            seq = transcript.coding_sequence
            if transcript.on_backward_strand:
                ref = reverse_complement(variant.ref)
                alt = reverse_complement(variant.alt)
            else:
                ref = variant.ref
                alt = variant.alt
            # get offsets into coding sequence by subtracting off
            # untranslated region lengths
            # TODO: move subtraction of 5' UTR length into
            # pyensembl.Transcript, call the method "coding_offset"
            positions = [
                transcript.spliced_offset(pos),
                transcript.spliced_offset(end_pos)
            ]
            start_offset_with_utr5 = min(positions)
            end_offset_with_utr5 = max(positions)

            assert start_offset_with_utr5 >= 0, \
                "Position %d is before start of transcript %s" % (
                    start_offset_with_utr5, transcript)
            assert end_offset_with_utr5 >= 0, \
                "Position %d is before start of transcript %s" % (
                    end_offset_with_utr5, transcript)
            utr5_length = transcript.first_start_codon_spliced_offset
            if (utr5_length >= start_offset_with_utr5 and
                utr5_length >= end_offset_with_utr5):
                protein_variants[transcript.id] = "5' UTR"
                continue
            start_offset = start_offset_with_utr5 - utr5_length
            end_offset = end_offset_with_utr5 - utr5_length

            if start_offset >= len(seq) and end_offset >= len(seq):
                protein_variants[transcript.id] = "3' UTR"
                continue

            original_dna = seq[start_offset:end_offset+1]

            # indexing into Sequence objects gives us another Sequence,
            # but we actually just need an ordinary string
            original_dna = str(original_dna)
            assert original_dna == ref, \
                "Expected ref '%s', got '%s' in %s (offset %d:%d)" % (
                    ref,
                    original_dna, variant,
                    start_offset, end_offset)

            aa_position = start_offset / 3
            if len(original_dna) - len(alt) % 3 != 0:
                variant_string = "%dfs" % aa_position
            else:

                original_aa = "V"
                new_aa = "E"
                variant_string = "%s%d%s" % (original_aa, aa_position, new_aa)
            protein_variants[transcript.id] = "coding %s" % variant_string

        n_coding = sum(
            descriptor.startswith("coding")
            for descriptor
            in protein_variants.values())

        if n_coding > 0:
            variant_type = "coding"
        else:
            variant_type = "non-coding"

        return Annot(
            variant=variant,
            variant_type=variant_type,
            genes=overlapping_genes,
            transcripts=overlapping_transcripts,
            coding_effects=protein_variants)
