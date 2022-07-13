from typer import Argument, Option, Typer, echo

from .polaris_db import get_existing_history_txs_ids
from .processed_txs_handler import VelaTxHistoryHandler

cli = Typer(name="Transaction History Migration", no_args_is_help=True)

# pylint: disable=too-complex,too-many-locals
@cli.command(no_args_is_help=True)
def run(
    retailer_slug: str = Argument(...),
    polaris_db_name: str = Option("polaris"),
    batch_size: int = Option(1000, min=10, max=5000),
    debug: bool = Option(False, help="If set to True logs the activity payload instead of sending it."),
    max_txs_to_process: int = Option(None, min=1, help="Maximum number of transactions to process."),
) -> None:
    echo("Starting script...")

    current_batch = 0  # pylint: disable=invalid-name
    existing_history_txs_ids = get_existing_history_txs_ids(polaris_db_name, retailer_slug)

    with VelaTxHistoryHandler(retailer_slug, existing_history_txs_ids, debug=debug) as handler:
        tx_to_process_count = handler.get_processed_tx_count()

        msg = f"{tx_to_process_count:d} transactions to process, will process in batches of {batch_size:d}"

        tot_tx_to_process = tx_to_process_count
        if max_txs_to_process:
            msg += f" up to {max_txs_to_process:d} transactions."

            if max_txs_to_process < tx_to_process_count:
                tot_tx_to_process = max_txs_to_process

        remaining_txs_n = tot_tx_to_process
        estimated_tot_batches = tot_tx_to_process // batch_size
        if tot_tx_to_process % batch_size != 0:
            estimated_tot_batches += 1

        echo(msg)
        try:
            while True:
                current_batch += 1
                next_batch_size = batch_size if remaining_txs_n >= batch_size else remaining_txs_n

                processed_txs_data = handler.fetch_batch(next_batch_size)
                if not processed_txs_data:
                    break

                echo(f"processing batch {current_batch:d}/{estimated_tot_batches:d}")
                for tx_data in processed_txs_data:
                    handler.produce_activity(tx_data)

                remaining_txs_n -= next_batch_size
                if remaining_txs_n <= 0:
                    break

        except KeyboardInterrupt:
            echo("Script manually interupted, exiting...")

    echo("Finished.")


@cli.callback()
def callback() -> None:
    """
    command line interface
    """


if __name__ == "__main__":
    cli()
