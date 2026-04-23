"""
Textbook-aligned abstract model for GNSS signal representation and tracking loops.

Purpose
-------
This module does not replace the current receiver implementation. It exists as a
reference model layer that captures the textbook decomposition of:

1. GNSS signal structure
2. Received/baseband signal representation
3. Carrier tracking loop structure
4. Code tracking loop structure
5. Natural receiver measurements
6. Mapping from natural measurements to navigation observables

Reference baseline
------------------
The abstractions below are aligned to the structure emphasized in
Kaplan/Hegarty, *Understanding GPS/GNSS Principles and Applications*:

- Chapter 2.4: GNSS signals
- Chapter 8.6: Carrier tracking
- Chapter 8.7: Code tracking
- Chapter 8.10: Formation of pseudorange, delta pseudorange,
  and integrated Doppler

Important textbook point
------------------------
The textbook treats the natural measurements of the receiver as:

- replica code phase / inferred transmit time
- replica carrier Doppler phase or replica carrier Doppler frequency

and not pseudorange itself.

Project mapping
---------------
Current project code lives mainly in:

- src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py
- src/nav_ka/legacy/exp_multisat_wls_pvt_report.py
- src/nav_ka/legacy/exp_dynamic_multisat_ekf_report.py

This module records how the current design maps to the textbook model without
modifying any existing behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


C_LIGHT = 299_792_458.0


class SignalComponentKind(str, Enum):
    DATA = "data"
    PILOT = "pilot"


class ModulationKind(str, Enum):
    BPSK = "bpsk"
    BPSK_R = "bpsk_r"
    DSSS = "dsss"
    BOC = "boc"


class CarrierLoopKind(str, Enum):
    FLL = "fll"
    PLL = "pll"
    COSTAS_PLL = "costas_pll"
    FLL_ASSISTED_PLL = "fll_assisted_pll"


class CodeLoopKind(str, Enum):
    NONCOHERENT_DLL = "noncoherent_dll"
    QUASI_COHERENT_DLL = "quasi_coherent_dll"
    COHERENT_DLL = "coherent_dll"


class MeasurementKind(str, Enum):
    REPLICA_CODE_PHASE = "replica_code_phase"
    REPLICA_CARRIER_PHASE = "replica_carrier_phase"
    REPLICA_CARRIER_FREQUENCY = "replica_carrier_frequency"
    TRANSMIT_TIME = "transmit_time"
    PSEUDORANGE = "pseudorange"
    DELTA_PSEUDORANGE = "delta_pseudorange"
    INTEGRATED_DOPPLER = "integrated_doppler"


@dataclass(frozen=True)
class TextbookSectionRef:
    topic: str
    pdf_page_start: int
    note: str


@dataclass(frozen=True)
class SignalStructureModel:
    """
    Abstract signal structure before receiver tracking details are applied.
    """

    carrier_frequency_hz: float
    chipping_rate_hz: float
    code_length_chips: int
    modulation: tuple[ModulationKind, ...]
    components: tuple[SignalComponentKind, ...]
    has_navigation_data: bool
    has_pilot_component: bool
    has_secondary_code: bool
    uses_complex_envelope_representation: bool
    textbook_refs: tuple[TextbookSectionRef, ...] = field(default_factory=tuple)

    @property
    def code_period_s(self) -> float:
        return self.code_length_chips / self.chipping_rate_hz

    @property
    def wavelength_m(self) -> float:
        return C_LIGHT / self.carrier_frequency_hz


@dataclass(frozen=True)
class ReceivedSignalStateModel:
    """
    State variables that a textbook signal model keeps explicit at receiver input.
    """

    receive_time_s: float
    amplitude: float
    carrier_phase_rad: float
    carrier_doppler_hz: float
    code_phase_chips: float
    code_phase_rate_chips_per_s: float
    navigation_symbol: int | None
    additive_noise_present: bool
    propagation_phase_term_rad: float
    propagation_group_delay_s: float


@dataclass(frozen=True)
class CorrelatorLayoutModel:
    """
    Correlator bank arrangement used by tracking loops.
    """

    uses_early_prompt_late: bool
    early_late_spacing_chips: float
    prompt_used_by_carrier_loop: bool
    extra_correlators_supported: bool
    note: str


@dataclass(frozen=True)
class CarrierDiscriminatorModel:
    kind: CarrierLoopKind
    discriminator_input: str
    discriminator_output: str
    supports_data_modulation: bool
    textbook_pull_in_comment: str
    note: str


@dataclass(frozen=True)
class CarrierLoopModel:
    """
    Abstract carrier loop structure.

    The textbook distinguishes:
    - FLL for robust pull-in and dynamic stress tolerance
    - PLL for dataless pilot tracking
    - Costas PLL for data-modulated channels
    - FLL-assisted PLL during transition or stress
    """

    loop_kind: CarrierLoopKind
    discriminator: CarrierDiscriminatorModel
    predetection_integration_s: float
    loop_filter_order: int | None
    bandwidth_strategy: str
    tracks_phase_lock: bool
    tracks_frequency_lock: bool
    output_state_variables: tuple[str, ...]
    textbook_refs: tuple[TextbookSectionRef, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CodeDiscriminatorModel:
    kind: CodeLoopKind
    discriminator_equation_name: str
    discriminator_input: str
    normalized: bool
    requires_carrier_phase_lock: bool
    note: str


@dataclass(frozen=True)
class CodeLoopModel:
    """
    Abstract code loop structure.

    The textbook emphasizes that coherent code tracking is only valid when the
    carrier loop is in phase lock. Noncoherent or quasi-coherent forms are more
    robust when phase lock is not guaranteed.
    """

    loop_kind: CodeLoopKind
    discriminator: CodeDiscriminatorModel
    correlator_layout: CorrelatorLayoutModel
    carrier_aiding_expected: bool
    predetection_integration_s: float
    loop_filter_order: int | None
    output_state_variables: tuple[str, ...]
    textbook_refs: tuple[TextbookSectionRef, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class NaturalMeasurementModel:
    """
    Natural measurements before navigation-layer observable construction.
    """

    measurement_kind: MeasurementKind
    state_source: str
    units: str
    textbook_role: str


@dataclass(frozen=True)
class ObservableConstructionModel:
    """
    Mapping from natural measurements to navigation observables.
    """

    output_measurement_kind: MeasurementKind
    required_natural_measurements: tuple[MeasurementKind, ...]
    additional_inputs: tuple[str, ...]
    note: str
    textbook_refs: tuple[TextbookSectionRef, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CurrentImplementationMapping:
    """
    Explicit mapping between the textbook model and the current project design.
    """

    current_file: str
    current_symbols: tuple[str, ...]
    textbook_alignment: str
    deviation_or_simplification: str


@dataclass(frozen=True)
class GnssSignalTrackingTextbookModel:
    signal_structure: SignalStructureModel
    correlator_layout: CorrelatorLayoutModel
    carrier_loop: CarrierLoopModel
    code_loop: CodeLoopModel
    natural_measurements: tuple[NaturalMeasurementModel, ...]
    observable_construction: tuple[ObservableConstructionModel, ...]
    current_mappings: tuple[CurrentImplementationMapping, ...]


def build_current_project_signal_tracking_model() -> GnssSignalTrackingTextbookModel:
    """
    Build a textbook-aligned abstraction of the current project design.

    This function is intentionally descriptive rather than executable.
    """

    signal_structure = SignalStructureModel(
        carrier_frequency_hz=22.5e9,
        chipping_rate_hz=50e3,
        code_length_chips=127,
        modulation=(ModulationKind.DSSS, ModulationKind.BPSK_R),
        components=(SignalComponentKind.DATA,),
        has_navigation_data=False,
        has_pilot_component=False,
        has_secondary_code=False,
        uses_complex_envelope_representation=True,
        textbook_refs=(
            TextbookSectionRef("GNSS Signals", 67, "Carrier, DSSS, BPSK/BPSK-R, signal model"),
            TextbookSectionRef("Signal Models and Characteristics", 74, "Complex-envelope representation"),
        ),
    )

    correlator_layout = CorrelatorLayoutModel(
        uses_early_prompt_late=True,
        early_late_spacing_chips=0.50,
        prompt_used_by_carrier_loop=True,
        extra_correlators_supported=False,
        note=(
            "Current implementation uses a classic E/P/L bank with one prompt carrier"
            " discriminator input and one noncoherent early-minus-late code discriminator."
        ),
    )

    carrier_loop = CarrierLoopModel(
        loop_kind=CarrierLoopKind.FLL_ASSISTED_PLL,
        discriminator=CarrierDiscriminatorModel(
            kind=CarrierLoopKind.COSTAS_PLL,
            discriminator_input="prompt correlator P = I_P + j Q_P",
            discriminator_output="phase error in radians",
            supports_data_modulation=True,
            textbook_pull_in_comment=(
                "Textbook suggests FLL for pull-in and gradual transition to Costas PLL"
                " on data channels."
            ),
            note=(
                "Current code uses atan2(Q_P, |I_P|) Costas phase discriminator and adds"
                " short-term FLL assistance from adjacent prompt samples."
            ),
        ),
        predetection_integration_s=1e-3,
        loop_filter_order=None,
        bandwidth_strategy=(
            "fixed PI-like frequency update with optional FLL assist and explicit limits"
        ),
        tracks_phase_lock=True,
        tracks_frequency_lock=True,
        output_state_variables=(
            "carrier_freq_hz",
            "carrier_phase_total_rad",
            "carrier_phase_start_rad",
            "pll_integrator_hz",
        ),
        textbook_refs=(
            TextbookSectionRef("Carrier Tracking", 458, "FLL/PLL/Costas decomposition"),
            TextbookSectionRef("Carrier Loop Discriminator", 459, "Prompt I/Q drives carrier discriminator"),
        ),
    )

    code_loop = CodeLoopModel(
        loop_kind=CodeLoopKind.NONCOHERENT_DLL,
        discriminator=CodeDiscriminatorModel(
            kind=CodeLoopKind.NONCOHERENT_DLL,
            discriminator_equation_name="normalized early-minus-late envelope",
            discriminator_input="E and L correlator magnitudes",
            normalized=True,
            requires_carrier_phase_lock=False,
            note=(
                "Current implementation uses (|E|-|L|)/(|E|+|L|), which matches the"
                " textbook noncoherent normalized DLL family."
            ),
        ),
        correlator_layout=correlator_layout,
        carrier_aiding_expected=True,
        predetection_integration_s=1e-3,
        loop_filter_order=None,
        output_state_variables=("tau_est_s",),
        textbook_refs=(
            TextbookSectionRef("Code Tracking", 465, "DLL as the code-tracking loop"),
            TextbookSectionRef("Code Loop Discriminators", 466, "Normalized noncoherent E-L discriminator"),
        ),
    )

    natural_measurements = (
        NaturalMeasurementModel(
            measurement_kind=MeasurementKind.REPLICA_CODE_PHASE,
            state_source="receiver replica code state / tau_est_s",
            units="seconds or chips",
            textbook_role="Natural code measurement before pseudorange construction",
        ),
        NaturalMeasurementModel(
            measurement_kind=MeasurementKind.REPLICA_CARRIER_PHASE,
            state_source="carrier_phase_total_rad",
            units="radians or cycles",
            textbook_role="Natural carrier phase measurement when in phase lock",
        ),
        NaturalMeasurementModel(
            measurement_kind=MeasurementKind.REPLICA_CARRIER_FREQUENCY,
            state_source="carrier_freq_hz",
            units="hertz",
            textbook_role="Natural carrier frequency measurement when in frequency lock",
        ),
        NaturalMeasurementModel(
            measurement_kind=MeasurementKind.TRANSMIT_TIME,
            state_source="replica code phase interpreted against receiver time tagging",
            units="seconds",
            textbook_role="Textbook-preferred interface into navigation processing",
        ),
    )

    observable_construction = (
        ObservableConstructionModel(
            output_measurement_kind=MeasurementKind.PSEUDORANGE,
            required_natural_measurements=(
                MeasurementKind.TRANSMIT_TIME,
            ),
            additional_inputs=("common receive time tag",),
            note=(
                "Textbook pseudorange is constructed from receive time minus inferred"
                " satellite transmit time, not treated as the receiver's raw natural output."
            ),
            textbook_refs=(
                TextbookSectionRef("Formation of Pseudorange", 508, "Natural measurements are not pseudorange"),
                TextbookSectionRef("Pseudorange", 510, "rho_i = c [T_R(n) - T_Ti(n)]"),
            ),
        ),
        ObservableConstructionModel(
            output_measurement_kind=MeasurementKind.INTEGRATED_DOPPLER,
            required_natural_measurements=(
                MeasurementKind.REPLICA_CARRIER_PHASE,
            ),
            additional_inputs=("carrier phase continuity management",),
            note="Integrated Doppler is derived from replica carrier phase accumulation.",
            textbook_refs=(
                TextbookSectionRef("Formation of Integrated Doppler", 509, "Replica carrier phase is the natural source"),
            ),
        ),
        ObservableConstructionModel(
            output_measurement_kind=MeasurementKind.DELTA_PSEUDORANGE,
            required_natural_measurements=(
                MeasurementKind.REPLICA_CARRIER_FREQUENCY,
                MeasurementKind.REPLICA_CARRIER_PHASE,
            ),
            additional_inputs=("time differencing convention",),
            note="Delta pseudorange is derived from carrier phase/frequency measurement states.",
            textbook_refs=(
                TextbookSectionRef("Formation of Delta Pseudorange", 509, "Carrier Doppler phase/frequency as natural source"),
            ),
        ),
    )

    current_mappings = (
        CurrentImplementationMapping(
            current_file="src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py",
            current_symbols=(
                "SignalConfig",
                "TrackingConfig",
                "ReceiverState",
                "correlate_block",
                "dll_discriminator",
                "costas_pll_discriminator",
                "run_tracking",
            ),
            textbook_alignment=(
                "Uses textbook-like signal/baseband decomposition plus E/P/L correlation,"
                " noncoherent DLL, and Costas-based carrier loop."
            ),
            deviation_or_simplification=(
                "Carrier loop filter is implemented as a practical PI-style update with"
                " explicit clamps rather than a separately formalized loop-filter model."
            ),
        ),
        CurrentImplementationMapping(
            current_file="src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py",
            current_symbols=("pseudorange_m", "carrier_phase_cycles", "doppler_hz"),
            textbook_alignment=(
                "Exports navigation-style observables after tracking."
            ),
            deviation_or_simplification=(
                "Receiver raw natural measurements are not exposed as a dedicated layer;"
                " tau_est_s, carrier_phase_total_rad, and carrier_freq_hz are present but"
                " not formalized as the canonical measurement interface."
            ),
        ),
        CurrentImplementationMapping(
            current_file="src/nav_ka/legacy/exp_multisat_wls_pvt_report.py",
            current_symbols=("pseudorange_m",),
            textbook_alignment=(
                "Correctly states that DLL output c * tau_est is not itself the standard"
                " navigation pseudorange."
            ),
            deviation_or_simplification=(
                "Transmit-time style receiver interface is not yet passed explicitly into"
                " the navigation layer."
            ),
        ),
    )

    return GnssSignalTrackingTextbookModel(
        signal_structure=signal_structure,
        correlator_layout=correlator_layout,
        carrier_loop=carrier_loop,
        code_loop=code_loop,
        natural_measurements=natural_measurements,
        observable_construction=observable_construction,
        current_mappings=current_mappings,
    )


CURRENT_PROJECT_SIGNAL_TRACKING_TEXTBOOK_MODEL = build_current_project_signal_tracking_model()
