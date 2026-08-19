"""
Production CLI for AI Code Detector.

Provides command-line interface with subcommands for scanning,
CI/CD integration, and remediation.
"""

import argparse
import sys
import json
from pathlib import Path
from typing import Optional

from codebase_csi import __version__, AICodeDetector
from codebase_csi.core.models import ScanConfiguration
from codebase_csi.utils.logger import setup_logging, get_logger


logger = get_logger(__name__)


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser with all commands."""
    parser = argparse.ArgumentParser(
        prog='ai-detector',
        description='AI Code Detector - Detect and analyze AI-generated code patterns',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scan a single file
  ai-detector scan myfile.py
  
  # Scan a directory
  ai-detector scan /path/to/project
  
  # Scan with custom threshold
  ai-detector scan /path/to/project --threshold 0.5
  
  # Generate JSON report
  ai-detector scan /path/to/project --format json --output report.json
  
  # CI/CD mode (exit 1 if quality gates fail)
  ai-detector cicd /path/to/project --max-confidence 0.6
  
  # Enable all enterprise features
  ai-detector scan /path/to/project --enterprise
  
For more information, visit: https://github.com/ai-code-detector/ai-code-detector
        """
    )
    
    parser.add_argument(
        '--version',
        action='version',
        version=f'%(prog)s {__version__}'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose output (DEBUG level)'
    )
    
    # Create subcommands
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Scan command
    scan_parser = subparsers.add_parser(
        'scan',
        help='Scan files or directories for AI-generated code'
    )
    add_scan_arguments(scan_parser)
    
    # CI/CD command
    cicd_parser = subparsers.add_parser(
        'cicd',
        help='Run in CI/CD mode with quality gates'
    )
    add_cicd_arguments(cicd_parser)
    
    # Remediate command
    remediate_parser = subparsers.add_parser(
        'remediate',
        help='Generate remediation suggestions'
    )
    add_remediate_arguments(remediate_parser)
    
    # Config command
    config_parser = subparsers.add_parser(
        'config',
        help='Manage configuration'
    )
    add_config_arguments(config_parser)
    
    return parser


def add_scan_arguments(parser: argparse.ArgumentParser):
    """Add arguments for scan command."""
    parser.add_argument(
        'path',
        type=str,
        help='File or directory to scan'
    )
    
    parser.add_argument(
        '-t', '--threshold',
        type=float,
        default=0.4,
        help='Confidence threshold for reporting (0.0-1.0, default: 0.4)'
    )
    
    parser.add_argument(
        '-f', '--format',
        choices=['text', 'json', 'yaml', 'html'],
        default='text',
        help='Output format (default: text)'
    )
    
    parser.add_argument(
        '-o', '--output',
        type=str,
        help='Output file path (default: stdout)'
    )
    
    parser.add_argument(
        '--extensions',
        nargs='+',
        help='File extensions to scan (e.g., .py .js .ts)'
    )
    
    parser.add_argument(
        '--exclude',
        nargs='+',
        help='Patterns to exclude (e.g., "node_modules/*" "*.min.js")'
    )
    
    parser.add_argument(
        '--max-file-size',
        type=int,
        default=1024,
        help='Maximum file size in KB (default: 1024)'
    )
    
    parser.add_argument(
        '--enterprise',
        action='store_true',
        help='Enable all enterprise features'
    )
    
    parser.add_argument(
        '--no-recursive',
        action='store_true',
        help='Do not scan subdirectories'
    )
    
    parser.add_argument(
        '--detailed',
        action='store_true',
        help='Generate detailed report with code snippets and remediation guidance'
    )


def add_cicd_arguments(parser: argparse.ArgumentParser):
    """Add arguments for CI/CD command."""
    parser.add_argument(
        'path',
        type=str,
        help='Directory to scan'
    )
    
    parser.add_argument(
        '--max-confidence',
        type=float,
        default=0.6,
        help='Maximum allowed AI confidence (default: 0.6)'
    )
    
    parser.add_argument(
        '--max-percentage',
        type=float,
        default=30.0,
        help='Maximum allowed percentage of AI files (default: 30.0)'
    )
    
    parser.add_argument(
        '--provider',
        choices=['github', 'gitlab', 'jenkins', 'generic'],
        default='generic',
        help='CI/CD provider for formatted output'
    )
    
    parser.add_argument(
        '--report',
        type=str,
        help='Path to save detailed report'
    )


def add_remediate_arguments(parser: argparse.ArgumentParser):
    """Add arguments for remediate command."""
    parser.add_argument(
        'scan_result',
        type=str,
        help='Path to scan result JSON file'
    )
    
    parser.add_argument(
        '-o', '--output',
        type=str,
        help='Output file for remediation plan'
    )
    
    parser.add_argument(
        '--priority',
        choices=['all', 'critical', 'high', 'medium'],
        default='all',
        help='Minimum priority level to include'
    )


def add_config_arguments(parser: argparse.ArgumentParser):
    """Add arguments for config command."""
    parser.add_argument(
        'action',
        choices=['show', 'init', 'validate'],
        help='Configuration action'
    )
    
    parser.add_argument(
        '--file',
        type=str,
        help='Configuration file path'
    )


def command_scan(args) -> int:
    """Execute scan command."""
    logger.info(f"Scanning: {args.path}")
    
    # Create configuration
    config = ScanConfiguration(
        confidence_threshold=args.threshold,
        output_format=args.format,
        verbose=args.verbose,
        max_file_size_kb=args.max_file_size
    )
    
    if args.extensions:
        config.include_extensions = args.extensions
    
    if args.exclude:
        config.exclude_patterns = args.exclude
    
    if args.enterprise:
        config.enable_remediation = True
        config.enable_quality_gates = True
        config.enable_compliance_report = True
    
    # Create detector
    try:
        detector = AICodeDetector(config)
    except ValueError as e:
        logger.error(f"Invalid configuration: {e}")
        return 1
    
    # Scan target
    path = Path(args.path)
    
    try:
        if path.is_file():
            # Scan single file
            result = detector.scan_file(path)
            print(f"\nFile: {result.file_path}")
            print(f"Language: {result.language}")
            print(f"Confidence: {result.confidence_level.value} ({result.confidence_score:.2%})")
            print(f"Patterns: {result.pattern_count}")
            
            if result.patterns:
                print("\nTop Patterns:")
                for pattern in result.high_confidence_patterns[:5]:
                    print(f"  Line {pattern.line_number}: {pattern.pattern_type} ({pattern.confidence:.2%})")
        
        elif path.is_dir():
            # Scan directory
            recursive = not args.no_recursive
            result = detector.scan_directory(path, recursive=recursive)
            
            # Format output
            if args.format == 'json':
                # Use detailed report if requested (includes code snippets and remediation)
                if hasattr(args, 'detailed') and args.detailed:
                    output = json.dumps(result.get_detailed_report(), indent=2)
                else:
                    output = json.dumps(result.get_summary(), indent=2)
            elif args.format == 'text':
                output = format_text_report(result)
            else:
                output = f"Format '{args.format}' not yet implemented"
            
            # Write output
            if args.output:
                Path(args.output).write_text(output)
                logger.info(f"Report saved to: {args.output}")
            else:
                print(output)
        
        else:
            logger.error(f"Path not found: {path}")
            return 1
        
        return 0
    
    except Exception as e:
        logger.error(f"Scan failed: {e}", exc_info=args.verbose)
        return 1


def command_cicd(args) -> int:
    """Execute CI/CD command."""
    logger.info(f"Running CI/CD scan: {args.path}")
    
    # Create configuration with quality gates
    config = ScanConfiguration(
        enable_quality_gates=True,
        max_ai_confidence=args.max_confidence,
        max_ai_file_percentage=args.max_percentage,
        verbose=args.verbose
    )
    
    # Create detector
    detector = AICodeDetector(config)
    
    # Run analysis
    try:
        analysis = detector.analyze_project(Path(args.path))
        
        # Print results based on provider
        print_cicd_results(analysis, args.provider)
        
        # Save report if requested
        if args.report:
            with open(args.report, 'w') as f:
                json.dump(analysis.get_executive_summary(), f, indent=2)
            logger.info(f"Report saved to: {args.report}")
        
        # Exit with appropriate code
        if analysis.quality_gate_passed:
            logger.info("✓ Quality gates PASSED")
            return 0
        else:
            logger.error("✗ Quality gates FAILED")
            for failure in analysis.quality_gate_failures:
                logger.error(f"  - {failure}")
            return 1
    
    except Exception as e:
        logger.error(f"CI/CD scan failed: {e}", exc_info=args.verbose)
        return 1


def command_remediate(args) -> int:
    """Execute remediate command."""
    logger.info(f"Generating remediation plan: {args.scan_result}")
    
    try:
        # Load scan result
        with open(args.scan_result) as f:
            scan_data = json.load(f)
        
        # Generate remediation plan
        print("Remediation feature coming soon!")
        return 0
    
    except Exception as e:
        logger.error(f"Remediation failed: {e}")
        return 1


def command_config(args) -> int:
    """Execute config command."""
    if args.action == 'show':
        config = ScanConfiguration()
        print(json.dumps(config.__dict__, indent=2, default=str))
    elif args.action == 'init':
        print("Config initialization coming soon!")
    elif args.action == 'validate':
        print("Config validation coming soon!")
    
    return 0


def format_text_report(result) -> str:
    """Format detection result as text report."""
    lines = []
    lines.append("=" * 80)
    lines.append("AI CODE DETECTION REPORT")
    lines.append("=" * 80)
    lines.append(f"\nScan ID: {result.scan_id}")
    lines.append(f"Target: {result.target_path}")
    lines.append(f"Timestamp: {result.timestamp.isoformat()}")
    lines.append(f"\nFiles Scanned: {result.scanned_files}")
    lines.append(f"AI-Generated Files: {result.ai_file_count} ({result.ai_percentage:.1f}%)")
    lines.append(f"Overall Confidence: {result.overall_confidence:.2%}")
    lines.append(f"Total Patterns: {result.total_patterns}")
    lines.append(f"Scan Duration: {result.scan_duration_seconds:.2f}s")
    
    if result.ai_generated_files:
        lines.append("\n" + "=" * 80)
        lines.append("AI-GENERATED FILES")
        lines.append("=" * 80)
        
        for file_analysis in result.ai_generated_files[:20]:  # Top 20
            lines.append(f"\n{file_analysis.file_path}")
            lines.append(f"  Confidence: {file_analysis.confidence_level.value} ({file_analysis.confidence_score:.2%})")
            lines.append(f"  Patterns: {file_analysis.pattern_count}")
            lines.append(f"  Language: {file_analysis.language}")
    
    lines.append("\n" + "=" * 80)
    return "\n".join(lines)


def print_cicd_results(analysis, provider: str):
    """Print CI/CD results in provider-specific format."""
    if provider == 'github':
        # GitHub Actions format
        if not analysis.quality_gate_passed:
            for failure in analysis.quality_gate_failures:
                print(f"::error::{failure}")
    elif provider == 'gitlab':
        # GitLab CI format
        if not analysis.quality_gate_passed:
            for failure in analysis.quality_gate_failures:
                print(f"ERROR: {failure}")
    else:
        # Generic format
        print(f"Quality Gate: {'PASSED' if analysis.quality_gate_passed else 'FAILED'}")
        if not analysis.quality_gate_passed:
            print("\nFailures:")
            for failure in analysis.quality_gate_failures:
                print(f"  - {failure}")


def main() -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(
        level='DEBUG' if args.verbose else 'INFO',
        verbose=args.verbose
    )
    
    # Execute command
    if not args.command:
        parser.print_help()
        return 0
    
    commands = {
        'scan': command_scan,
        'cicd': command_cicd,
        'remediate': command_remediate,
        'config': command_config
    }
    
    command_func = commands.get(args.command)
    if command_func:
        try:
            return command_func(args)
        except KeyboardInterrupt:
            logger.info("\nOperation cancelled by user")
            return 130
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=args.verbose)
            return 1
    else:
        parser.print_help()
        return 1


if __name__ == '__main__':
    sys.exit(main())
